"""GUARDIA A3 — robustezza del RENDERER VIDEO e degli UPLOADER SOCIAL.

Copre collaudi/video_render.py + collaudi/pubblica_video.py + collaudi/giro_video.py:
  - asset corrotti (scarica_immagine: payload corti, pagine HTML, magic bytes, tentativi);
  - proporzioni (cover + center-crop SEMPRE, MAI scale che deforma, canvas coerente con W/H);
  - audio (aac 44100 stereo su ogni encoding, +faststart sul concat finale);
  - testo (expansion=none ovunque, guardia anti-tofu _font -> None + degrade a EN,
    incluso il FORMATO LUNGO a 7 scene: difetto vero corretto — prima IndexError);
  - coerenza lingua (voce e schermo mai misti, chiusura sempre fissa, niente {citta} residui);
  - uploader (multipart ben formato — giudice stdlib email —, mai eccezioni su rete rotta,
    sendVideo con supports_streaming, cerchietto 640, caption col 3% sempre dichiarato).

Gira SENZA rete e SENZA ffmpeg/edge-tts: subprocess (_run), urlopen e sleep sono iniettati
finti; si verificano le STRINGHE dei comandi costruiti e la logica pura. Deterministico.

Visto ROSSO: ogni guardia e' stata provata rossa rompendo temporaneamente la stringa
corrispondente nei tre moduli (dettaglio nel report A3), poi il codice e' stato ripristinato
byte-per-byte (checksum confrontato con la copia pristina).
"""
import contextlib
import email
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, os.path.join(_ROOT, "collaudi")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import video_render as V            # noqa: E402
import pubblica_video as P          # noqa: E402
import giro_video as G              # noqa: E402


def _tariffa_tecnica_del_motore():
    """La tariffa tecnica in percento, LETTA dal default di `main_casavip.py`.
    Non si scrive a mano: una cifra incisa dentro un test invecchia al primo cambio e
    fa diventare rosso un codice giusto (successo il 2026-08-10, 3% -> 5%).
    Se non la trova NON tira a indovinare: fa fallire la prova con un motivo chiaro."""
    _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                      if os.path.basename(os.path.dirname(os.path.abspath(__file__))) == "collaudi"
                      else os.path.dirname(os.path.abspath(__file__)), "main_casavip.py")
    with io.open(_p, encoding="utf-8", errors="replace") as _f:
        _m = re.search(r'PAGAMENTO_BPS["\']\s*,\s*["\'](\d+)["\']', _f.read())
    if not _m:
        raise AssertionError("PAGAMENTO_BPS non trovato in main_casavip.py: questa prova "
                             "non e' in condizione di misurare e si ferma")
    return int(_m.group(1)) // 100

JPEG = b"\xff\xd8\xff" + b"\x00" * 4000
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4000

# scale=W:H "secco" (senza force_original_aspect_ratio SUBITO dopo) = deformazione:
# (?=[,:\[]|$) obbliga il match sull'intera coppia W:H (niente backtracking su "180" di "1800")
_SCALE_DEFORMANTE = re.compile(r"scale=\d+:\d+(?=[,:\[]|$)(?!:force_original_aspect_ratio)")


class _Resp:
    """Risposta HTTP finta: context manager con .read() (bytes o dict->JSON)."""

    def __init__(self, dati):
        self._dati = dati if isinstance(dati, bytes) else json.dumps(dati).encode("utf-8")

    def read(self):
        return self._dati

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _RunFinto:
    """_run iniettato: registra ogni comando; per ffmpeg crea il file d'uscita (ultimo arg)."""

    def __init__(self):
        self.comandi = []

    def __call__(self, cmd, **kw):
        self.comandi.append(list(cmd))
        if cmd and cmd[0] == "ffmpeg":
            with open(cmd[-1], "wb") as f:
                f.write(b"\x00" * 64)

        class _P:
            returncode, stdout, stderr = 0, "", ""
        return _P()


def _vf(cmd):
    """Estrae la stringa-filtro (-filter_complex o -vf) da un comando ffmpeg registrato."""
    for flag in ("-filter_complex", "-vf"):
        if flag in cmd:
            return cmd[cmd.index(flag) + 1]
    return ""


def _coppia(cmd, flag, valore):
    """True se il comando contiene la coppia consecutiva flag valore."""
    return any(cmd[i] == flag and cmd[i + 1] == valore for i in range(len(cmd) - 1))


def _harness_monta(citta="Roma", lingua="it", nota=False, font_none=False, groq=None):
    """Esegue monta()/monta_nota() con TUTTO iniettato finto (niente rete/ffmpeg/sleep).
    Ritorna dict: comandi registrati, out_path, cartelle temporanee interne, stdout, base."""
    run = _RunFinto()
    base = tempfile.mkdtemp(prefix="tvid_")
    out_path = os.path.join(base, "out.mp4")
    interni = []
    vero_mkdtemp = tempfile.mkdtemp

    def mkdtemp_reg(prefix="x"):
        d = vero_mkdtemp(prefix=prefix, dir=base)
        interni.append(d)
        return d

    def img_finta(sogg, dest):
        with open(dest, "wb") as f:
            f.write(JPEG)
        return True

    def voce_finta(testo, voce, dest):
        with open(dest, "wb") as f:
            f.write(b"\x00" * 32)
        return 2.0

    buf = io.StringIO()
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.object(V, "_run", run))
        st.enter_context(mock.patch.object(V, "_env", lambda nome, default="": ""))
        st.enter_context(mock.patch.object(V, "scarica_immagine", img_finta))
        st.enter_context(mock.patch.object(V, "sintetizza_voce", voce_finta))
        st.enter_context(mock.patch.object(V.tempfile, "mkdtemp", mkdtemp_reg))
        st.enter_context(mock.patch.object(V.time, "sleep", lambda s: None))
        if font_none:
            st.enter_context(mock.patch.object(V, "_font", lambda lingua_schermo: None))
        if groq is not None:
            st.enter_context(mock.patch.object(V, "_groq_copione",
                                               lambda *a, **k: list(groq)))
        st.enter_context(contextlib.redirect_stdout(buf))
        (V.monta_nota if nota else V.monta)(citta, lingua, out_path)
    return {"comandi": run.comandi, "out": out_path, "interni": interni,
            "stdout": buf.getvalue(), "base": base}


# ────────────────────────── ASSET CORROTTI: scarica_immagine ──────────────────────────
class TestAssetCorrotti(unittest.TestCase):

    def _scarica(self, risposte):
        """risposte: lista di bytes|Exception, una per tentativo.
        Ritorna (esito, dest, n_chiamate_rete, pause_sleep)."""
        base = tempfile.mkdtemp(prefix="timg_")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        dest = os.path.join(base, "img.jpg")
        it = iter(risposte)
        conta = {"n": 0}

        def urlopen_finto(req, timeout=None):
            conta["n"] += 1
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return _Resp(r)

        pause = []
        with mock.patch.object(V.urllib.request, "urlopen", urlopen_finto), \
                mock.patch.object(V.time, "sleep", lambda s: pause.append(s)):
            ok = V.scarica_immagine("test subject", dest)
        return ok, dest, conta["n"], pause

    def test_payload_corto_rifiutato(self):
        # magic JPEG giusti ma solo pochi byte (thumbnail troncata / errore) -> False, file MAI scritto
        ok, dest, _, _ = self._scarica([b"\xff\xd8\xff" + b"x" * 10] * 6)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(dest))

    def test_pagina_html_di_errore_rifiutata(self):
        # una pagina d'errore HTML lunga NON e' un'immagine
        html = b"<html><body><h1>503 Service Unavailable</h1></body></html>" + b" " * 4000
        ok, dest, _, _ = self._scarica([html] * 6)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(dest))

    def test_magic_bytes_sbagliati_rifiutati(self):
        # payload lungo ma con firma non JPEG/PNG (es. GIF) -> False
        ok, dest, _, _ = self._scarica([b"GIF89a" + b"\x00" * 5000] * 6)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(dest))

    def test_jpeg_vero_accettato_e_scritto(self):
        ok, dest, n, _ = self._scarica([JPEG])
        self.assertTrue(ok)
        self.assertEqual(n, 1)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), JPEG)

    def test_png_vero_accettato(self):
        ok, dest, _, _ = self._scarica([PNG])
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(dest))

    def test_rete_rotta_mai_solleva_e_rispetta_i_tentativi(self):
        # urlopen esplode SEMPRE: niente eccezione fuori, ESATTAMENTE 6 tentativi,
        # 5 pause da 15s fra i falliti + il garbo iniziale da 3s
        ok, dest, n, pause = self._scarica([OSError("rete giu")] * 6)
        self.assertFalse(ok)
        self.assertEqual(n, 6)
        self.assertEqual(pause.count(15), 5)
        self.assertEqual(pause.count(3), 1)

    def test_riprova_e_poi_riesce(self):
        ok, dest, n, _ = self._scarica([OSError("giu"), b"corto", JPEG])
        self.assertTrue(ok)
        self.assertEqual(n, 3)


# ─────────────────────────── PROPORZIONI: cover + center-crop ───────────────────────────
class TestProporzioni(unittest.TestCase):

    def _clip(self, nota=False, hint="Sound on"):
        run = _RunFinto()
        base = tempfile.mkdtemp(prefix="tclip_")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        img = os.path.join(base, "i.jpg")
        mp3 = os.path.join(base, "v.mp3")
        with open(img, "wb") as f:
            f.write(JPEG)
        with open(mp3, "wb") as f:
            f.write(b"\x00" * 16)
        with mock.patch.object(V, "_run", run):
            if nota:
                V.clip_nota(img, mp3, 4.0, "0% commissioni\nper 90 giorni", base, 0,
                            font="/font/DejaVuSans-Bold.ttf")
            else:
                V.clip_scena(img, mp3, 4.0, "0% commissioni\nper 90 giorni", base, 0,
                             font="/font/DejaVuSans-Bold.ttf", hint=hint)
        self.assertEqual(len(run.comandi), 1)
        return run.comandi[0]

    def test_clip_scena_cover_e_center_crop(self):
        vf = _vf(self._clip())
        self.assertIn("force_original_aspect_ratio=increase", vf)
        # subito dopo il cover DEVE esserci il crop (center-crop, mai deformare)
        self.assertRegex(vf, r"force_original_aspect_ratio=increase[^,]*,crop=\d+:\d+")

    def test_clip_scena_nessuno_scale_deformante(self):
        vf = _vf(self._clip())
        self.assertIsNone(_SCALE_DEFORMANTE.search(vf), "scale che deforma in: %s" % vf)

    def test_clip_scena_canvas_coerente_con_modulo(self):
        vf = _vf(self._clip())
        self.assertIn("s=%dx%d" % (V.W, V.H), vf)     # zoompan sul canvas W/H del modulo
        self.assertEqual(V.W % 2, 0)                   # libx264/yuv420p esige dimensioni pari
        self.assertEqual(V.H % 2, 0)

    def test_clip_nota_cover_e_canvas_640(self):
        vf = _vf(self._clip(nota=True))
        self.assertIn("force_original_aspect_ratio=increase", vf)
        self.assertRegex(vf, r"force_original_aspect_ratio=increase[^,]*,crop=640:640")
        self.assertIsNone(_SCALE_DEFORMANTE.search(vf), "scale che deforma in: %s" % vf)

    def test_monta_ogni_scena_ha_cover_mai_deformazioni(self):
        r = _harness_monta()                           # it -> formato lungo, 7 scene
        enc = [c for c in r["comandi"] if _vf(c)]
        self.assertEqual(len(enc), 7)
        for c in enc:
            vf = _vf(c)
            self.assertIn("force_original_aspect_ratio=increase", vf)
            self.assertIsNone(_SCALE_DEFORMANTE.search(vf), "scale che deforma in: %s" % vf)
        # l'invito «attiva l'audio» c'e' SOLO sulla prima scena
        self.assertEqual(sum(1 for c in enc if "hint" in _vf(c)), 1)
        shutil.rmtree(r["base"], ignore_errors=True)


# ─────────────────────────────── AUDIO: standard social ───────────────────────────────
class TestAudio(unittest.TestCase):

    def _controlla_audio(self, cmd):
        self.assertTrue(_coppia(cmd, "-c:a", "aac"), cmd)
        self.assertTrue(_coppia(cmd, "-ar", "44100"), cmd)
        self.assertTrue(_coppia(cmd, "-ac", "2"), cmd)

    def test_ogni_encoding_di_monta_ha_audio_standard(self):
        r = _harness_monta()
        enc = [c for c in r["comandi"] if _vf(c)]
        self.assertEqual(len(enc), 7)
        for c in enc:
            self._controlla_audio(c)
        shutil.rmtree(r["base"], ignore_errors=True)

    def test_ogni_encoding_di_monta_nota_ha_audio_standard(self):
        r = _harness_monta(citta="Tokyo", lingua="ja", nota=True)   # ja ripiego -> 5 scene
        enc = [c for c in r["comandi"] if _vf(c)]
        self.assertEqual(len(enc), 5)
        for c in enc:
            self._controlla_audio(c)
        shutil.rmtree(r["base"], ignore_errors=True)

    def test_concat_finale_ha_faststart(self):
        for kw in ({}, {"nota": True, "citta": "Tokyo", "lingua": "ja"}):
            r = _harness_monta(**kw)
            concat = [c for c in r["comandi"] if "concat" in c]
            self.assertEqual(len(concat), 1)
            self.assertTrue(_coppia(concat[0], "-movflags", "+faststart"), concat[0])
            self.assertTrue(os.path.exists(r["out"]))
            shutil.rmtree(r["base"], ignore_errors=True)


# ──────────────────────────── TESTO: expansion=none + anti-tofu ────────────────────────────
class TestTesto(unittest.TestCase):

    def _chunk_drawtext(self, vf):
        return vf.split("drawtext=")[1:]

    def test_expansion_none_ovunque_si_disegna_testo(self):
        # clip_scena (testo + hint), clip_nota e TUTTE le scene di monta
        vfs = []
        run = _RunFinto()
        base = tempfile.mkdtemp(prefix="texp_")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        img, mp3 = os.path.join(base, "i.jpg"), os.path.join(base, "v.mp3")
        with open(img, "wb") as f:
            f.write(JPEG)
        with open(mp3, "wb") as f:
            f.write(b"\x00" * 16)
        with mock.patch.object(V, "_run", run):
            V.clip_scena(img, mp3, 4.0, "0%", base, 0, font="/f.ttf", hint="Sound on")
            V.clip_nota(img, mp3, 4.0, "0%", base, 1, font="/f.ttf")
        vfs += [_vf(c) for c in run.comandi]
        r = _harness_monta()
        vfs += [_vf(c) for c in r["comandi"] if _vf(c)]
        shutil.rmtree(r["base"], ignore_errors=True)
        totale = 0
        for vf in vfs:
            for chunk in self._chunk_drawtext(vf):
                totale += 1
                self.assertIn("expansion=none", chunk,
                              "drawtext SENZA expansion=none (il %% verrebbe mangiato): " + vf)
        self.assertGreaterEqual(totale, 10)   # la guardia deve aver visto davvero i drawtext

    def test_font_speciale_mancante_ritorna_none(self):
        with mock.patch.object(V.os.path, "exists", lambda p: False):
            for lingua in V.FONT_LINGUA:
                self.assertIsNone(V._font(lingua), lingua)

    def test_font_speciale_presente_ritorna_il_font(self):
        with mock.patch.object(V.os.path, "exists", lambda p: True):
            for lingua in V.FONT_LINGUA:
                self.assertEqual(V._font(lingua), V.FONT_LINGUA[lingua][0])

    def test_font_lingue_latine_e_cirillico_dejavu(self):
        for lingua in ("it", "en", "es", "fr", "de", "pt", "nl", "tr", "ru", "id", "vi"):
            self.assertEqual(V._font(lingua), V.FONT)

    def test_lingue_a_font_speciale_hanno_schermo_e_arabo_no(self):
        # ja/zh/ko/th hanno testi a schermo dedicati; l'arabo NON va a schermo
        # (drawtext non fa lo shaping RTL) e non deve avere font dedicato
        self.assertTrue(set(V.FONT_LINGUA) <= set(V.SCHERMO))
        self.assertNotIn("ar", V.SCHERMO)
        self.assertNotIn("ar", V.FONT_LINGUA)

    def test_monta_degrada_schermo_a_inglese_senza_font(self):
        # ja col ripiego (5 scene classiche): senza font CJK lo schermo diventa inglese
        r = _harness_monta(citta="Tokyo", lingua="ja", font_none=True)
        self.addCleanup(shutil.rmtree, r["base"], ignore_errors=True)
        tmp = r["interni"][0]
        for i in range(5):
            with open(os.path.join(tmp, "t%d.txt" % i), encoding="utf-8") as f:
                self.assertEqual(f.read(), V._riempi(V.SCHERMO["en"][i], "Tokyo"))
        with open(os.path.join(tmp, "hint0.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), V.AUDIO_HINT["en"])

    def test_monta_degrada_anche_il_formato_lungo(self):
        # DIFETTO VERO corretto: copione AI (7 scene) + font thai assente -> prima IndexError
        # (SCHERMO["en"] ha 5 voci), il video non veniva MAI reso. Ora ogni scena degrada.
        r = _harness_monta(citta="Bangkok", lingua="th", font_none=True,
                           groq=["a", "b", "c", "d", "e", "f"])
        self.addCleanup(shutil.rmtree, r["base"], ignore_errors=True)
        tmp = r["interni"][0]
        leva_nome, _ = V._leva_rotante("Bangkok")
        attesi = ([V._riempi(t, "Bangkok") for t in V.SCHERMO["en"][:4]]
                  + [V.CONTO_SCHERMO["en"], V.LEVA_SCHERMO[leva_nome]["en"]]
                  + [V._riempi(V.SCHERMO["en"][4], "Bangkok")])
        for i, atteso in enumerate(attesi):
            with open(os.path.join(tmp, "t%d.txt" % i), encoding="utf-8") as f:
                self.assertEqual(f.read(), atteso, "scena %d" % (i + 1))

    def test_copione_porta_il_ripiego_inglese_per_scena(self):
        scene, _, _, _ = V.copione(None, "Roma", "it")
        leva_nome, _ = V._leva_rotante("Roma")
        self.assertEqual(scene[4]["schermo_en"], V.CONTO_SCHERMO["en"])
        self.assertEqual(scene[5]["schermo_en"], V.LEVA_SCHERMO[leva_nome]["en"])
        for s in scene:
            self.assertIn("schermo_en", s)
            self.assertNotIn("{citta}", s["schermo_en"])


# ───────────────────────── COERENZA LINGUA: copione() mai misto ─────────────────────────
class TestCoerenzaLingua(unittest.TestCase):

    def test_ripiego_italiano_lungo_e_chiusura_fissa(self):
        scene, da_ai, lv, ls = V.copione(None, "Roma", "it")
        self.assertFalse(da_ai)
        self.assertEqual((lv, ls), ("it", "it"))
        self.assertEqual(len(scene), 7)
        self.assertEqual(scene[-1]["voce"], V.CHIUSURA_VOCE["it"])
        self.assertEqual(scene[4]["voce"], V.PSICO_VOCE_RIPIEGO["it"]["conto"])

    def test_lingua_senza_ripiego_degrada_tutta_a_inglese(self):
        # ko non ha VOCE_RIPIEGO: voce E schermo passano INSIEME all'inglese (mai misti)
        scene, da_ai, lv, ls = V.copione(None, "Seoul", "ko")
        self.assertFalse(da_ai)
        self.assertEqual((lv, ls), ("en", "en"))
        self.assertEqual(len(scene), 7)
        self.assertEqual(scene[0]["voce"], "Do you own a place in Seoul?")
        self.assertEqual(scene[0]["schermo"], "Seoul.")
        self.assertEqual(scene[4]["schermo"], V.CONTO_SCHERMO["en"])
        self.assertEqual(scene[-1]["voce"], V.CHIUSURA_VOCE["en"])

    def test_giapponese_classico_coerente(self):
        # ja ha il ripiego voce ma non il blocco psicologico -> formato classico a 5, tutto ja
        scene, da_ai, lv, ls = V.copione(None, "Tokyo", "ja")
        self.assertFalse(da_ai)
        self.assertEqual((lv, ls), ("ja", "ja"))
        self.assertEqual(len(scene), 5)
        self.assertEqual(scene[1]["voce"], V.VOCE_RIPIEGO["ja"][1])
        self.assertEqual(scene[-1]["voce"], V.CHIUSURA_VOCE["ja"])

    def test_nessun_residuo_citta_e_voci_mai_vuote(self):
        for lingua in sorted(set(V.VOCI) | {"xx"}):
            scene, _, lv, ls = V.copione(None, "Testville", lingua)
            self.assertIn(lv, V.VOCE_RIPIEGO, lingua)              # mai una terza lingua
            self.assertEqual(ls, lv if lv in V.SCHERMO else "en", lingua)
            self.assertIn(len(scene), (5, 7), lingua)
            self.assertEqual(scene[-1]["voce"],
                             V.CHIUSURA_VOCE.get(lv, V.CHIUSURA_VOCE["en"]), lingua)
            self.assertIn("Testville", scene[0]["soggetto"], lingua)
            for s in scene:
                for campo in ("soggetto", "schermo", "schermo_en", "voce"):
                    self.assertNotIn("{citta}", s[campo], "%s/%s" % (lingua, campo))
                self.assertTrue(s["voce"], "voce vuota (%s)" % lingua)

    def test_chiusura_fissa_anche_con_ai(self):
        # anche quando l'AI scrive il copione, l'ULTIMA battuta resta la frase curata
        battute = ["v1", "v2", "v3", "v4", "v5", "v6"]
        with mock.patch.object(V, "_groq_copione", lambda *a, **k: list(battute)):
            scene, da_ai, lv, ls = V.copione("chiave-finta", "Paris", "fr")
        self.assertTrue(da_ai)
        self.assertEqual((lv, ls), ("fr", "fr"))
        self.assertEqual(len(scene), 7)
        self.assertEqual([s["voce"] for s in scene[:6]], battute)
        self.assertEqual(scene[-1]["voce"], V.CHIUSURA_VOCE["fr"])
        self.assertEqual(scene[4]["schermo"], V.CONTO_SCHERMO["fr"])

    def test_chiusure_e_voci_coprono_tutte_le_lingue(self):
        self.assertTrue(set(V.VOCI) <= set(V.CHIUSURA_VOCE))
        self.assertTrue(set(V.VOCE_RIPIEGO) <= set(V.CHIUSURA_VOCE))

    def _groq(self, contenuto, lingua="de", n=5, solleva=False):
        def urlopen_finto(req, timeout=None):
            if solleva:
                raise OSError("rete giu")
            return _Resp({"choices": [{"message": {"content": contenuto}}]})

        with mock.patch.object(V.urllib.request, "urlopen", urlopen_finto), \
                contextlib.redirect_stdout(io.StringIO()):
            return V._groq_copione("chiave-finta", "Berlin", lingua, n)

    def test_groq_scarta_italiano_fuori_italia(self):
        # guardiano-lingua: una battuta italiana in un copione tedesco -> TUTTO scartato
        self.assertIsNone(self._groq("eins|zwei|pubblica la casa|vier|fuenf"))
        # lo stesso testo in Italia e' lecito
        self.assertEqual(len(self._groq("pubblica la tua casa|due|tre|quattro|cinque",
                                        lingua="it")), 5)

    def test_groq_battute_pulite_o_niente(self):
        self.assertEqual(self._groq("eins|zwei|drei|vier|fuenf"),
                         ["eins", "zwei", "drei", "vier", "fuenf"])
        self.assertIsNone(self._groq("eins|zwei"))                 # troppo poche -> ripiego

    def test_groq_mai_solleva(self):
        self.assertIsNone(self._groq("x", solleva=True))           # rete giu -> None, mai crash
        self.assertIsNone(V._groq_copione("", "Roma", "it", 5))    # senza chiave: niente rete


# ──────────────────────────── UPLOADER: multipart + mai crash ────────────────────────────
class TestUploader(unittest.TestCase):

    def _file_video(self, dati=b"FINTO-MP4" * 8):
        base = tempfile.mkdtemp(prefix="tup_")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        path = os.path.join(base, "v.mp4")
        with open(path, "wb") as f:
            f.write(dati)
        return path, dati

    def _env(self, valori):
        return mock.patch.object(P, "_env", lambda nome, default="": valori.get(nome, ""))

    def test_multipart_ben_formato_giudice_stdlib(self):
        dati = b"\x00\x01BINARIO\r\n--finto--\xff\xfe"
        boundary, corpo = P._multipart({"chat_id": "42", "caption": "ciao mondo"},
                                       {"video": ("v.mp4", dati, "video/mp4")})
        self.assertTrue(boundary.startswith("----BVIP"))
        self.assertGreater(len(boundary), 20)
        self.assertNotIn(boundary.encode(), dati)
        # terminatore multipart obbligatorio
        self.assertTrue(corpo.endswith(("--%s--\r\n" % boundary).encode()))
        # headers del file ben separati dal corpo (riga vuota CRLF CRLF)
        self.assertIn(b'name="video"; filename="v.mp4"\r\nContent-Type: video/mp4\r\n\r\n',
                      corpo)
        # GIUDICE ESTERNO stdlib: il parser email deve rileggere le 3 parti INTATTE
        msg = email.message_from_bytes(
            b"Content-Type: multipart/form-data; boundary=" + boundary.encode()
            + b"\r\nMIME-Version: 1.0\r\n\r\n" + corpo)
        self.assertTrue(msg.is_multipart())
        parti = msg.get_payload()
        self.assertEqual(len(parti), 3)
        per_nome = {}
        for parte in parti:
            m = re.search(r'name="([^"]+)"', parte.get("Content-Disposition", ""))
            per_nome[m.group(1)] = parte
        self.assertEqual(per_nome["chat_id"].get_payload(decode=True), b"42")
        self.assertEqual(per_nome["caption"].get_payload(decode=True), b"ciao mondo")
        self.assertEqual(per_nome["video"].get_payload(decode=True), dati)
        self.assertEqual(per_nome["video"].get_content_type(), "video/mp4")

    def test_telegram_mai_solleva_su_rete_rotta(self):
        path, _ = self._file_video()

        def esplode(*a, **k):
            raise OSError("rete giu")

        with self._env({"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"}), \
                mock.patch.object(P, "_post_multipart", esplode):
            self.assertTrue(P.telegram(path, "cap").startswith("ERR"))
            self.assertTrue(P.telegram_nota(path).startswith("ERR"))

    def test_facebook_e_mastodon_mai_sollevano(self):
        path, _ = self._file_video()

        def esplode(*a, **k):
            raise OSError("rete giu")

        with self._env({"META_PAGE_ID": "P", "META_PAGE_TOKEN": "T"}), \
                mock.patch.object(P, "_post_multipart", esplode):
            self.assertTrue(P.facebook(path, "cap").startswith("ERR"))
        with self._env({"MASTODON_INSTANCE": "mastodon.social", "MASTODON_TOKEN": "T"}), \
                mock.patch.object(P.urllib.request, "urlopen", esplode), \
                mock.patch.object(P.time, "sleep", lambda s: None):
            self.assertTrue(P.mastodon(path, "cap").startswith("ERR"))

    def test_senza_token_niente_rete_niente_file(self):
        def bomba(*a, **k):
            raise AssertionError("rete/multipart toccati senza token")

        with self._env({}), \
                mock.patch.object(P.urllib.request, "urlopen", bomba), \
                mock.patch.object(P, "_post_multipart", bomba):
            for fn in (lambda: P.telegram("/inesistente/v.mp4", "c"),
                       lambda: P.telegram_nota("/inesistente/v.mp4"),
                       lambda: P.facebook("/inesistente/v.mp4", "c"),
                       lambda: P.mastodon("/inesistente/v.mp4", "c")):
                self.assertEqual(fn(), "no-token")

    def test_sendvideo_usa_supports_streaming(self):
        path, dati = self._file_video()
        visto = {}

        def registra(url, campi, files, timeout=240):
            visto.update(url=url, campi=campi, files=files)
            return {"ok": True, "result": {"message_id": 7}}

        with self._env({"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"}), \
                mock.patch.object(P, "_post_multipart", registra):
            self.assertEqual(P.telegram(path, "cap"), "OK id 7")
        self.assertIn("/sendVideo", visto["url"])
        self.assertEqual(visto["campi"].get("supports_streaming"), "true")
        fn, corpo, ct = visto["files"]["video"]
        self.assertEqual((fn, corpo, ct), ("v.mp4", dati, "video/mp4"))

    def test_video_note_endpoint_e_length_coerente_col_canvas(self):
        path, _ = self._file_video()
        visto = {}

        def registra(url, campi, files, timeout=240):
            visto.update(url=url, campi=campi, files=files)
            return {"ok": True, "result": {"message_id": 9}}

        with self._env({"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"}), \
                mock.patch.object(P, "_post_multipart", registra):
            self.assertEqual(P.telegram_nota(path), "OK id 9")
        self.assertIn("/sendVideoNote", visto["url"])
        self.assertIn("video_note", visto["files"])
        # il length dichiarato a Telegram DEVE combaciare col canvas 640 di clip_nota
        self.assertEqual(visto["campi"].get("length"), "640")

    def test_errore_api_ritorna_err_leggibile(self):
        path, _ = self._file_video()
        with self._env({"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"}), \
                mock.patch.object(P, "_post_multipart",
                                  lambda *a, **k: {"ok": False, "description": "chat not found"}):
            self.assertEqual(P.telegram(path, "cap"), "ERR chat not found")

    def test_mastodon_flusso_completo(self):
        path, dati = self._file_video()
        visite = []

        def urlopen_finto(req, timeout=None):
            url = req.full_url
            visite.append(url)
            if url.endswith("/api/v2/media"):
                # upload multipart: header con boundary + Bearer
                ct = req.get_header("Content-type", "")
                self.assertIn("multipart/form-data; boundary=", ct)
                self.assertEqual(req.get_header("Authorization"), "Bearer T")
                self.assertIn(dati, req.data)
                return _Resp({"id": "m1"})
            if url.endswith("/api/v1/media/m1"):
                return _Resp({"url": "https://mast/media/pronto"})
            if url.endswith("/api/v1/statuses"):
                corpo = json.loads(req.data.decode("utf-8"))
                self.assertEqual(corpo["media_ids"], ["m1"])
                self.assertEqual(corpo["visibility"], "public")
                return _Resp({"id": "s1", "url": "https://mast/@bv/1"})
            raise AssertionError("URL inatteso: " + url)

        with self._env({"MASTODON_INSTANCE": "mastodon.social", "MASTODON_TOKEN": "T"}), \
                mock.patch.object(P.urllib.request, "urlopen", urlopen_finto), \
                mock.patch.object(P.time, "sleep", lambda s: None):
            self.assertEqual(P.mastodon(path, "toot"), "OK https://mast/@bv/1")
        self.assertEqual(len(visite), 3)


# ─────────────────────────── GIRO: link tracciati e didascalie ───────────────────────────
class TestGiroVideo(unittest.TestCase):

    def test_link_utm_per_canale(self):
        link = G._link("roma", "telegram")
        self.assertTrue(link.startswith("https://bookinvip.com/affitta/roma?"))
        self.assertIn("utm_source=telegram", link)
        self.assertIn("utm_medium=video", link)
        self.assertIn("utm_campaign=host-roma", link)

    def test_caption_compilata_e_ripiego_inglese(self):
        c = G._caption("it", "Roma", "roma", "telegram")
        self.assertIn("Roma", c)
        self.assertIn("utm_source=telegram", c)
        self.assertNotIn("{", c)
        cx = G._caption("xx", "Testville", "testville", "mastodon")
        self.assertIn("Do you own a place in Testville?", cx)

    def test_la_tariffa_tecnica_sempre_dichiarata(self):
        """Regola d'oro del progetto: la tariffa tecnica va SEMPRE detta, in OGNI lingua
        (il francese scrive «5 %» con lo spazio, il turco «%5»: entrambi leciti).

        ⛔ Si chiamava `test_tre_percento_sempre_dichiarato` e cercava «3» a mano: il
        2026-08-10, passando al 5%, e' diventato rosso pur essendo GIUSTE sia le
        didascalie sia la regola. Il numero stava perfino nel NOME del test.
        Ora la cifra si prende DAL MOTORE: cosi' il test verifica la REGOLA («la tariffa
        e' dichiarata») invece della CIFRA DI QUEL GIORNO, e non invecchia piu'."""
        tec = _tariffa_tecnica_del_motore()
        for lingua, tpl in G.CAPTION.items():
            self.assertTrue(re.search(r"%d\s*%%|%%\s*%d" % (tec, tec), tpl),
                            "la tariffa tecnica (%d%%) non e' dichiarata in %s"
                            % (tec, lingua))
            self.assertIn("{c}", tpl, lingua)
            self.assertIn("{link}", tpl, lingua)
            compilata = tpl.format(c="X", link="Y")     # nessun segnaposto orfano
            self.assertNotIn("{", compilata, lingua)

    def test_tappe_coerenti_lingua_voce_slug(self):
        slugs = [t[0] for t in G.TAPPE]
        self.assertEqual(len(slugs), len(set(slugs)))            # mai la stessa tappa due volte
        for slug, citta, lingua, voce in G.TAPPE:
            self.assertTrue(slug and citta, slug)
            self.assertIn(lingua, G.CAPTION, slug)               # didascalia nella lingua
            self.assertTrue(lingua in V.VOCI or voce, slug)      # voce sempre disponibile


if __name__ == "__main__":
    unittest.main()
