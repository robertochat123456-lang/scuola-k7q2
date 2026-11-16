#!/usr/bin/env python3
"""Legge compiti e voti da Mastercom e scrive i file del sito (cartella docs):
  dati.json     compiti e argomenti
  compiti.ics   calendario per l'app Calendario di Apple
  voti.enc      voti CIFRATI con la password VOTI_PASS (illeggibili senza)
Si esegue una volta sola: a ripeterlo ogni 15 minuti pensa GitHub Actions."""
import os, re, json, base64, hashlib, getpass, datetime as dt

URL = "https://salesianifirenze.registroelettronico.com/mastercom/index.php"
QUI = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(QUI, "docs")
MESI = {m: i + 1 for i, m in enumerate("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split())}
GIORNI = {"lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"}
STATI = {"da fare", "fatto"}


CHIAVI = ["home", "voti", "compiti", "argomenti", "assenze", "note", "agenda", "orario", "colloqui",
          "pagelle", "comunicazioni", "messaggi", "scrutini", "bacheca", "materiale", "lezioni", "presenze"]


def menu_visibile(pg):
    """Elenca solo voci di menu note (mai nomi o dati personali)."""
    try:
        testi = pg.locator("a, button, [role=button], li").all_inner_texts()
    except Exception:
        return "?"
    viste = []
    for t in testi:
        t = " ".join(t.split())
        if 0 < len(t) < 40 and any(k in t.lower() for k in CHIAVI) and t not in viste:
            viste.append(t)
    return "; ".join(viste[:15]) or "nessuna voce riconosciuta"


def apri_voce(pg, nome, esatto=False):
    try:
        pg.get_by_text(nome, exact=esatto).first.click(timeout=3000)
        return
    except Exception:
        pass
    for sel in ["header button", "[class*=menu i]", "[class*=burger i]", "button", "[role=button]"]:
        try:
            pg.locator(sel).first.click(timeout=2000)
            pg.wait_for_timeout(800)
            pg.get_by_text(nome, exact=esatto).first.click(timeout=2500)
            return
        except Exception:
            continue
    raise RuntimeError(f"non trovo la voce '{nome}'. Pagina: {pg.url.split('?')[0]}. Voci viste: {menu_visibile(pg)}")


def scarica(utente, password):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 820, "height": 1180})
        try:
            pg.goto(URL, wait_until="networkidle")
            pw = pg.locator("input[type=password]").first
            pw.wait_for(timeout=20000)
            us = pg.locator("input:not([type=password]):not([type=hidden]):not([type=checkbox]):not([type=submit])").first
            us.click(); us.press_sequentially(utente, delay=40)
            pw.click(); pw.press_sequentially(password, delay=40)
            inviato = False
            for nome in ("Entra", "Accedi", "Login", "Invia", "Conferma"):
                bott = pg.get_by_role("button", name=nome, exact=True)
                if bott.count():
                    bott.first.click(); inviato = True
                    break
            if not inviato:
                pw.press("Enter")
            try:
                pw.wait_for(state="detached", timeout=20000)
            except Exception:
                pass
            pg.wait_for_load_state("networkidle")
            pg.wait_for_timeout(2500)
            campo = pg.locator("input[type=password]")
            if campo.count() and campo.first.is_visible():
                msg = ""
                try:
                    msg = pg.locator("[role=alert], [class*=error i], [class*=notif i], [class*=toast i]").first.inner_text(timeout=1500)[:100]
                except Exception:
                    pass
                raise RuntimeError("LOGIN NON RIUSCITO (mi fermo, non riprovo). Messaggio del sito: " + (msg or "nessuno"))
            try:
                apri_voce(pg, "Argomenti e Compiti")
            except RuntimeError as e:
                raise RuntimeError("LOGIN OK ma " + str(e))
            pg.wait_for_load_state("networkidle")
            pg.wait_for_timeout(2500)
            compiti = pg.inner_text("body")
            voti = None
            try:
                apri_voce(pg, "Voti", True)
                pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(2500)
                voti = pg.inner_text("body")
            except Exception as e:
                print("Voti non letti:", e)
            return compiti, voti
        finally:
            b.close()


def analizza(testo):
    righe = [r.strip() for r in testo.splitlines() if r.strip()]
    n, i = len(righe), 0
    voci, giorno, mese, materia, buf = [], None, None, "", []
    oggi = dt.date.today()
    while i < n:
        r = righe[i]
        prossima = righe[i + 1].lower() if i + 1 < n else ""
        if re.fullmatch(r"\d{1,2}", r) and prossima in MESI:
            giorno, mese, materia, buf = int(r), MESI[prossima], "", []
            i += 2
            if i < n and righe[i].lower() in GIORNI:
                i += 1
            continue
        if giorno is None:
            i += 1
            continue
        if r.lower() in STATI:
            fatto = r.lower() == "fatto"
            anno = oggi.year
            j = i + 1
            while j < min(i + 4, n):
                m = re.search(r"Inserito il (\d{2})/(\d{2})/(\d{4})", righe[j])
                if m:
                    anno = int(m.group(3))
                    if mese < int(m.group(2)):
                        anno += 1
                    break
                j += 1
            try:
                voci.append({"data": dt.date(anno, mese, giorno), "materia": materia, "testo": " ".join(buf), "fatto": fatto})
            except ValueError:
                pass
            buf = []
            i += 1
            while i < n and (righe[i].startswith("Inserito il") or righe[i].startswith("(")):
                i += 1
            continue
        if not buf and r.isupper() and prossima not in STATI and len(r) > 2:
            materia = r.title()
        else:
            buf.append(r)
        i += 1
    return [v for v in voci if v["testo"]]


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def piega(riga):
    b, out = riga.encode(), []
    while len(b) > 74:
        taglio = 74
        while taglio > 0 and (b[taglio] & 0xC0) == 0x80:
            taglio -= 1
        out.append(b[:taglio].decode()); b = b" " + b[taglio:]
    out.append(b.decode())
    return "\r\n".join(out)


def crea_ics(voci):
    r = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Mastercom calendario//IT",
         "X-WR-CALNAME:Scuola (Mastercom)", "REFRESH-INTERVAL;VALUE=DURATION:PT15M", "X-PUBLISHED-TTL:PT15M"]
    for v in voci:
        uid = hashlib.sha1(f"{v['data']}{v['materia']}{v['testo']}".encode()).hexdigest() + "@mastercom"
        titolo = (v["materia"] + ": " if v["materia"] else "") + v["testo"]
        if v["fatto"]:
            titolo = "✓ " + titolo
        r += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{v['data']:%Y%m%d}T000000Z",
              f"DTSTART;VALUE=DATE:{v['data']:%Y%m%d}",
              f"DTEND;VALUE=DATE:{v['data'] + dt.timedelta(days=1):%Y%m%d}",
              piega("SUMMARY:" + esc(titolo[:120])), piega("DESCRIPTION:" + esc(titolo)), "END:VEVENT"]
    r.append("END:VCALENDAR")
    return "\r\n".join(r) + "\r\n"


def cifra(testo, pw):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    dati = testo.encode()
    salt = hashlib.sha256(b"mastercom-voti" + pw.encode()).digest()[:16]
    iv = hashlib.sha256(salt + dati).digest()[:12]     # stesso testo = stesso file: niente commit inutili
    chiave = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200000).derive(pw.encode())
    b64 = lambda x: base64.b64encode(x).decode()
    return json.dumps({"s": b64(salt), "i": b64(iv), "c": b64(AESGCM(chiave).encrypt(iv, dati, None))})


def main():
    utente = os.environ.get("MC_USER") or input("Utente Mastercom: ")
    password = os.environ.get("MC_PASS") or getpass.getpass("Password Mastercom: ")
    pw_voti = os.environ.get("VOTI_PASS", "")
    compiti, voti = scarica(utente, password)
    voci = analizza(compiti)
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "dati.json"), "w", encoding="utf-8") as f:
        json.dump({"voci": [{"d": v["data"].isoformat(), "m": v["materia"], "t": v["testo"], "f": v["fatto"]} for v in voci]}, f, ensure_ascii=False, indent=0)
    with open(os.path.join(DOCS, "compiti.ics"), "w", encoding="utf-8", newline="") as f:
        f.write(crea_ics(voci))
    if voti and len(pw_voti) >= 12:
        with open(os.path.join(DOCS, "voti.enc"), "w", encoding="utf-8") as f:
            f.write(cifra(voti, pw_voti))
        print("voti salvati (cifrati)")
    elif voti:
        print("Voti letti ma NON salvati: serve il segreto VOTI_PASS di almeno 12 caratteri")
    print(f"aggiornato, {len(voci)} voci")


if __name__ == "__main__":
    main()
