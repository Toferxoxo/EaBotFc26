"""
EA FC 26 - Bot de gangas y errores de precio
Parámetros optimizados — solo jugadores top de grandes ligas
"""

import requests
import schedule
import time
import random
import re
from datetime import datetime
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────

DISCORD_WEBHOOK  = "https://discord.com/api/webhooks/1503891250921603113/5lU8DMXH3bv9OxTWZDsFYopKu-wzIYPMGAdBlb2PvncPOpmZ9WMdpKTGb5-yEfJnmBuM"
TELEGRAM_TOKEN   = "8292663793:AAGhIU_jjo1TtX79KW_jrn-fUjtRUmYO79I"
TELEGRAM_CHAT_ID = "1849057975"

# ── Parámetros optimizados ──
PRECIO_LIMITE       = 750_000   # especiales y TOTS bajo este precio = ganga real
DESCUENTO_MINIMO    = 0.50      # 50% más barato = error de precio creíble
OVR_MINIMO          = 88        # solo jugadores 88+ OVR para errores de liga
OVR_MINIMO_TOTS     = 94        # TOTS: solo 94+ OVR
PRECIO_LIMITE_TOTY  = 300_000   # TOTY masculino: bajo 300K = error de precio
PRECIO_LIMITE_TOTS  = 300_000   # TOTS 94+: bajo 300K = error de precio real
PRECIO_MINIMO_ERROR = 20_000    # ignorar jugadores que normalmente ya son baratos

INTERVALO_ESPECIALES_MIN = 5
INTERVALO_ERRORES_MIN    = 5
INTERVALO_TOTS_MIN       = 5

# ── Solo las 5 grandes ligas ──
LIGAS = {
    "Premier League": "13",
    "La Liga":        "53",
    "Bundesliga":     "19",
    "Serie A":        "31",
    "Ligue 1":        "16",
}

# ── Especiales clásicos (Icon y Hero usan PRECIO_LIMITE) ──
TIPOS_ESPECIALES = {
    "Icon": "icon",
    "Hero": "hero",
}

# ── TOTY masculino con su propio límite más estricto ──
# toty incluye ambos géneros en FUTBIN — filtramos femenino por nombre
TOTY_VERSION = "toty"
# Jugadoras del WOTOTY a excluir
WOTOTY_EXCLUIR = {
    "christiane endler", "millie bright", "selma bacha", "linda sembrant",
    "alexia putellas", "aitana bonmati", "caroline graham hansen",
    "trinity rodman", "linda caicedo", "sophia smith", "sam kerr",
    "vivianne miedema", "pernille harder", "wendie renard", "griedge mbock",
    "kadidiatou diani", "marie-antoinette katoto", "sakina karchaoui",
}

# ── TOTS de las ligas que importan ──
TOTS_ACTIVOS = {
    "TOTS Premier League": "PremierLeagueTOTS",
    "TOTS Bundesliga":     "BundesligaTOTS",
    "TOTS Ligue 1":        "Ligue1TOTS",
    "TOTS Serie A":        "SerieATOTS",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://www.futbin.com/",
}

# ─────────────────────────────────────────────
#  UTILIDADES
# ─────────────────────────────────────────────

def parsear_precio(texto: str) -> int:
    texto = texto.strip().upper()
    m = re.match(r"([\d.]+)\s*([MK]?)", texto)
    if not m:
        return 0
    try:
        num = float(m.group(1))
        sufijo = m.group(2)
        if sufijo == "M":
            return int(num * 1_000_000)
        if sufijo == "K":
            return int(num * 1_000)
        return int(num)
    except ValueError:
        return 0

def parsear_ovr(texto: str) -> int:
    try:
        return int(re.sub(r"\D", "", texto)[:2])
    except:
        return 0

def formatear_precio(precio: int) -> str:
    if precio >= 1_000_000:
        return f"{precio / 1_000_000:.2f}M"
    if precio >= 1_000:
        return f"{precio / 1_000:.0f}K"
    return f"{precio:,}"

def emoji_tipo(tipo: str) -> str:
    mapa = {
        "TOTY": "🏆", "Icon": "👑", "Hero": "🦸",
        "TOTS Premier League": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "TOTS Bundesliga":     "🇩🇪",
        "TOTS Ligue 1":        "🇫🇷",
        "TOTS Serie A":        "🇮🇹",
    }
    return mapa.get(tipo, "🌟")

def log(msg: str, nivel: str = "INFO"):
    ahora = datetime.now().strftime("%H:%M:%S")
    prefijos = {"INFO": "   ", "WARN": "⚠  ", "ERROR": "✗  "}
    print(f"[{ahora}] {prefijos.get(nivel, '')} {msg}")

def limpiar_nombre(raw: str) -> str:
    nombre = re.sub(r"^\d+", "", raw)
    nombre = re.sub(
        r"(TOTY|TOTS|Icon|Hero|Normal|Rare|Gold|Silver|Bronze|IF|POTM|RTTK|OTW|FUT).*$",
        "", nombre, flags=re.IGNORECASE
    ).strip()
    return nombre

def limpiar_posicion(raw: str) -> str:
    return re.split(r"[+\-]", raw)[0].strip()

def foto_jugador(url_futbin: str) -> str:
    m = re.search(r"/player/(d+)/", url_futbin)
    if m:
        return f"https://cdn.futbin.com/content/fc26/img/players/{m.group(1)}.png"
    return ""

def esc(s: str) -> str:
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(s))

# ─────────────────────────────────────────────
#  SCRAPING
# ─────────────────────────────────────────────

def scrape_pagina(url: str, tipo_label: str = "") -> list:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        filas = soup.select("table.players-table tbody tr, table.futbin-table tbody tr")
        cartas = []

        for fila in filas:
            celdas = fila.select("td")
            if len(celdas) < 5:
                continue

            nombre = limpiar_nombre(celdas[0].get_text(strip=True))
            if not nombre:
                continue

            ovr_raw  = celdas[1].get_text(strip=True)
            ovr      = parsear_ovr(ovr_raw)
            posicion = limpiar_posicion(celdas[2].get_text(strip=True))

            # Filtro OVR — solo jugadores top
            if ovr > 0 and ovr < OVR_MINIMO:
                continue

            celdas_pc = fila.select("td.platform-pc-only")
            precio_ltp = parsear_precio(celdas_pc[0].get_text(strip=True)) if celdas_pc else 0
            precio_avg = parsear_precio(celdas_pc[1].get_text(strip=True)) if len(celdas_pc) > 1 else 0

            if precio_ltp <= 0:
                continue

            link = fila.select_one("a[href*='/player/']")
            url_jugador = ("https://www.futbin.com" + link["href"]) if link else url

            cartas.append({
                "nombre":     nombre,
                "precio":     precio_ltp,
                "precio_avg": precio_avg if precio_avg > 0 else precio_ltp,
                "ovr":        str(ovr) if ovr > 0 else ovr_raw,
                "posicion":   posicion,
                "tipo":       tipo_label,
                "url":        url_jugador,
            })

        return cartas
    except Exception as e:
        log(f"Error scraping: {e}", nivel="ERROR")
        return []

def scrape_multipagina(url_base: str, tipo_label: str, max_paginas: int = 3) -> list:
    todas = []
    for pagina in range(1, max_paginas + 1):
        cartas = scrape_pagina(f"{url_base}&page={pagina}", tipo_label)
        if not cartas:
            break
        todas.extend(cartas)
        if len(cartas) < 20:
            break
        time.sleep(random.uniform(1.5, 3.0))
    return todas

# ─────────────────────────────────────────────
#  NOTIFICACIONES
# ─────────────────────────────────────────────

alertas_enviadas: set = set()

def ya_notificado(clave: str) -> bool:
    return clave in alertas_enviadas

def marcar_notificado(clave: str):
    alertas_enviadas.add(clave)

def limpiar_alertas(claves_activas: set, sufijo: str):
    claves_tipo = {k for k in alertas_enviadas if k.endswith(sufijo)}
    for clave in claves_tipo - claves_activas:
        alertas_enviadas.discard(clave)

def enviar_discord(jugador: dict, modo: str):
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    tipo  = jugador["tipo"]
    emoji = emoji_tipo(tipo)

    if modo == "error":
        descuento  = jugador.get("descuento", 0)
        precio_ref = jugador.get("precio_ref", 0)
        titulo = f"💥 ¡ERROR DE PRECIO! — {jugador['nombre']}"
        color  = 0xFF4444
        fields = [
            {"name": "🏟️ Liga",         "value": tipo,                                          "inline": True},
            {"name": "⭐ OVR",           "value": jugador.get("ovr", "?"),                      "inline": True},
            {"name": "🏃 Posición",      "value": jugador.get("posicion", "?"),                 "inline": True},
            {"name": "💰 Precio PC",     "value": f"**{formatear_precio(jugador['precio'])}**", "inline": True},
            {"name": "📊 Precio normal", "value": formatear_precio(precio_ref),                 "inline": True},
            {"name": "📉 Descuento",     "value": f"**{descuento*100:.0f}% más barato**",       "inline": True},
            {"name": "🔗 FUTBIN",        "value": f"[¡Comprar ahora!]({jugador['url']})",       "inline": False},
        ]
    else:
        titulo = f"{emoji} ¡GANGA DETECTADA! — {jugador['nombre']}"
        color  = 0xFFD700
        fields = [
            {"name": "🃏 Tipo",      "value": tipo,                                          "inline": True},
            {"name": "⭐ OVR",       "value": jugador.get("ovr", "?"),                      "inline": True},
            {"name": "🏃 Posición",  "value": jugador.get("posicion", "?"),                 "inline": True},
            {"name": "💰 Precio PC", "value": f"**{formatear_precio(jugador['precio'])}**", "inline": True},
            {"name": "🎯 Límite",    "value": formatear_precio(PRECIO_LIMITE),              "inline": True},
            {"name": "🔗 FUTBIN",    "value": f"[Ver jugador]({jugador['url']})",           "inline": True},
        ]

    foto = foto_jugador(jugador.get("url", ""))
    embed = {"title": titulo, "color": color, "fields": fields,
             "footer": {"text": f"EA FC 26 Price Bot • {ahora}"}}
    if foto:
        embed["thumbnail"] = {"url": foto}
        embed["image"]     = {"url": foto}

    payload = {
        "username": "EA FC 26 Price Bot",
        "avatar_url": "https://www.ea.com/favicon.ico",
        "embeds": [embed]
    }
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code not in (200, 204):
            log(f"Discord error {r.status_code}", nivel="WARN")
    except Exception as e:
        log(f"Discord excepción: {e}", nivel="ERROR")

def enviar_telegram(jugador: dict, modo: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    tipo  = jugador["tipo"]
    emoji = emoji_tipo(tipo)

    if modo == "error":
        descuento  = jugador.get("descuento", 0)
        precio_ref = jugador.get("precio_ref", 0)
        texto = (
            f"💥 *¡ERROR DE PRECIO\\!*\n\n"
            f"👤 *{esc(jugador['nombre'])}* \\| {esc(tipo)}\n"
            f"⭐ {esc(jugador.get('ovr','?'))} OVR \\| 🏃 {esc(jugador.get('posicion','?'))}\n\n"
            f"💰 Precio actual: *{esc(formatear_precio(jugador['precio']))}*\n"
            f"📊 Precio normal: {esc(formatear_precio(precio_ref))}\n"
            f"📉 Descuento: *{esc(f'{descuento*100:.0f}')}% más barato*\n\n"
            f"🔗 [¡Comprar ahora\\!]({jugador['url']})\n_{esc(ahora)}_"
        )
    else:
        texto = (
            f"{emoji} *¡GANGA DETECTADA\\!*\n\n"
            f"👤 *{esc(jugador['nombre'])}* \\| {esc(tipo)}\n"
            f"⭐ {esc(jugador.get('ovr','?'))} OVR \\| 🏃 {esc(jugador.get('posicion','?'))}\n\n"
            f"💰 Precio PC: *{esc(formatear_precio(jugador['precio']))} monedas*\n"
            f"🎯 Límite: {esc(formatear_precio(PRECIO_LIMITE))} monedas\n\n"
            f"🔗 [Ver en FUTBIN]({jugador['url']})\n_{esc(ahora)}_"
        )

    foto = foto_jugador(jugador.get("url", ""))

    try:
        if foto:
            # sendPhoto muestra la carta del jugador con el texto como caption
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                json={"chat_id": TELEGRAM_CHAT_ID, "photo": foto,
                      "caption": texto, "parse_mode": "MarkdownV2"},
                timeout=10
            )
            # Si la foto falla (URL inválida), caer en sendMessage
            if not r.ok:
                r = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHAT_ID, "text": texto,
                          "parse_mode": "MarkdownV2", "disable_web_page_preview": False},
                    timeout=10
                )
        else:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": texto,
                      "parse_mode": "MarkdownV2", "disable_web_page_preview": False},
                timeout=10
            )
        if not r.ok:
            log(f"Telegram error {r.status_code}: {r.text[:100]}", nivel="WARN")
    except Exception as e:
        log(f"Telegram excepción: {e}", nivel="ERROR")

def notificar(jugador: dict, clave: str, modo: str):
    if not ya_notificado(clave):
        log(f"    🚨 {jugador['nombre']} | {formatear_precio(jugador['precio'])} | {jugador.get('ovr','?')} OVR")
        enviar_discord(jugador, modo)
        time.sleep(1)
        enviar_telegram(jugador, modo)
        marcar_notificado(clave)

# ─────────────────────────────────────────────
#  MÓDULO 1 — ESPECIALES CLÁSICOS BAJO 750K
# ─────────────────────────────────────────────

def revisar_especiales():
    log(f"══ [ESPECIALES] Icon/Hero < {formatear_precio(PRECIO_LIMITE)} | TOTY masculino < {formatear_precio(PRECIO_LIMITE_TOTY)} ══")
    encontradas = 0

    # ── TOTY masculino: límite propio de 300K ──
    time.sleep(random.uniform(2.0, 4.0))
    cartas_toty = scrape_multipagina(
        f"https://www.futbin.com/26/players?version={TOTY_VERSION}&sort=PC_LTP&order=asc&minrating={OVR_MINIMO}",
        "TOTY", max_paginas=2
    )
    baratas_toty = [
        c for c in cartas_toty
        if 0 < c["precio"] < PRECIO_LIMITE_TOTY
        and c["nombre"].lower() not in WOTOTY_EXCLUIR
    ]
    log(f"  TOTY masculino: {len(cartas_toty)} jugadores | {len(baratas_toty)} bajo {formatear_precio(PRECIO_LIMITE_TOTY)}")
    claves_toty = set()
    for carta in baratas_toty:
        encontradas += 1
        clave = f"{carta['nombre']}|TOTY|especial"
        claves_toty.add(clave)
        notificar(carta, clave, modo="ganga")
    limpiar_alertas(claves_toty, "|TOTY|especial")

    # ── Icon y Hero: límite general de 750K ──
    for tipo_label, tipo_filtro in TIPOS_ESPECIALES.items():
        time.sleep(random.uniform(3.0, 5.0))
        url_base = f"https://www.futbin.com/26/players?version={tipo_filtro}&sort=PC_LTP&order=asc&minrating={OVR_MINIMO}"
        cartas = scrape_multipagina(url_base, tipo_label)
        baratas = [c for c in cartas if 0 < c["precio"] < PRECIO_LIMITE]
        log(f"  {tipo_label}: {len(cartas)} jugadores top | {len(baratas)} gangas")
        claves_activas = set()
        for carta in baratas:
            encontradas += 1
            clave = f"{carta['nombre']}|{tipo_label}|especial"
            claves_activas.add(clave)
            notificar(carta, clave, modo="ganga")
        limpiar_alertas(claves_activas, f"|{tipo_label}|especial")

    if encontradas == 0:
        log("  Sin especiales bajo el límite.")
    log(f"══ Próxima revisión especiales en {INTERVALO_ESPECIALES_MIN} min ══\n")

# ─────────────────────────────────────────────
#  MÓDULO 2 — ERRORES DE PRECIO EN 5 GRANDES LIGAS
# ─────────────────────────────────────────────

def revisar_errores_precio():
    log(f"══ [ERRORES] -{int(DESCUENTO_MINIMO*100)}% del precio normal | OVR {OVR_MINIMO}+ ══")
    encontrados = 0
    for liga_nombre, liga_id in LIGAS.items():
        time.sleep(random.uniform(3.0, 6.0))
        url_base = (
            f"https://www.futbin.com/26/players"
            f"?leagueId={liga_id}&sort=PC_LTP&order=asc"
        )
        cartas = scrape_multipagina(url_base, liga_nombre, max_paginas=2)
        errores = []
        for c in cartas:
            if c["precio_avg"] < PRECIO_MINIMO_ERROR:
                continue
            if c["precio_avg"] > 0:
                descuento = 1 - (c["precio"] / c["precio_avg"])
                if descuento >= DESCUENTO_MINIMO:
                    c["descuento"]  = descuento
                    c["precio_ref"] = c["precio_avg"]
                    errores.append(c)

        log(f"  {liga_nombre}: {len(cartas)} jugadores top | {len(errores)} errores")
        claves_activas = set()
        for carta in errores:
            encontrados += 1
            clave = f"{carta['nombre']}|{liga_nombre}|error"
            claves_activas.add(clave)
            notificar(carta, clave, modo="error")
        limpiar_alertas(claves_activas, f"|{liga_nombre}|error")

    if encontrados == 0:
        log("  Sin errores de precio.")
    log(f"══ Próxima revisión errores en {INTERVALO_ERRORES_MIN} min ══\n")

# ─────────────────────────────────────────────
#  MÓDULO 3 — TOTS GRANDES LIGAS BAJO 750K
# ─────────────────────────────────────────────

def revisar_tots():
    log(f"══ [TOTS 94+] Error de precio: OVR {OVR_MINIMO_TOTS}+ y < {formatear_precio(PRECIO_LIMITE_TOTS)} ══")
    encontradas = 0
    for tots_nombre, tots_version in TOTS_ACTIVOS.items():
        time.sleep(random.uniform(3.0, 5.0))
        url_base = (
            f"https://www.futbin.com/26/players"
            f"?version={tots_version}&sort=PC_LTP&order=asc&minrating={OVR_MINIMO_TOTS}"
        )
        cartas = scrape_multipagina(url_base, tots_nombre, max_paginas=2)

        # Solo los que tienen 94+ OVR y cuestan menos de 300K — eso es error de precio real
        errores = []
        for c in cartas:
            ovr_num = 0
            try:
                ovr_num = int(re.sub(r"\D", "", c.get("ovr", "0"))[:2])
            except:
                pass
            if ovr_num >= OVR_MINIMO_TOTS and 0 < c["precio"] < PRECIO_LIMITE_TOTS:
                c["descuento"]  = 0
                c["precio_ref"] = 0
                errores.append(c)

        log(f"  {tots_nombre}: {len(cartas)} jugadores 94+ | {len(errores)} errores bajo {formatear_precio(PRECIO_LIMITE_TOTS)}")
        claves_activas = set()
        for carta in errores:
            encontradas += 1
            clave = f"{carta['nombre']}|{tots_nombre}|tots"
            claves_activas.add(clave)
            notificar(carta, clave, modo="ganga")
        limpiar_alertas(claves_activas, f"|{tots_nombre}|tots")

    if encontradas == 0:
        log(f"  Sin TOTS 94+ bajo {formatear_precio(PRECIO_LIMITE_TOTS)}.")
    log(f"══ Próxima revisión TOTS en {INTERVALO_TOTS_MIN} min ══\n")

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    log("═══════════════════════════════════════════")
    log("   EA FC 26 Price Bot — Parámetros top")
    log("═══════════════════════════════════════════")
    log(f"  OVR mínimo ligas:  {OVR_MINIMO}+")
    log(f"  OVR mínimo TOTS:   {OVR_MINIMO_TOTS}+ (error si < {formatear_precio(PRECIO_LIMITE_TOTS)})")
    log(f"  Límite especiales: < {formatear_precio(PRECIO_LIMITE)}")
    log(f"  Error de precio:   -{int(DESCUENTO_MINIMO*100)}% del precio normal")
    log(f"  Ligas:             {', '.join(LIGAS.keys())}")
    log(f"  TOTS activos:      {', '.join(TOTS_ACTIVOS.keys())}")
    log(f"  Discord:           {'✓' if DISCORD_WEBHOOK else '✗'}")
    log(f"  Telegram:          {'✓' if TELEGRAM_TOKEN else '✗'}")
    log("═══════════════════════════════════════════\n")

    revisar_errores_precio()
    revisar_tots()
    revisar_especiales()

    schedule.every(INTERVALO_ESPECIALES_MIN).minutes.do(revisar_especiales)
    schedule.every(INTERVALO_ERRORES_MIN).minutes.do(revisar_errores_precio)
    schedule.every(INTERVALO_TOTS_MIN).minutes.do(revisar_tots)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()