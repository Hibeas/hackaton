import requests
import folium
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# Wklej swoj klucz API
TOMTOM_API_KEY = "Eeuz6XPvDckP0avEfM50keYMPdgsWmNG"

# Trójmiasto — bbox incydentów
BBOX_TROJMIASTO = "18.4000,54.3000,18.7500,54.6000"

# Przykładowa trasa do analizy objazdu (lat,lon)
ROUTE_ORIGIN = "54.3520,18.6466"       # Gdańsk (centrum)
ROUTE_DESTINATION = "54.5189,18.5305"  # Gdynia (centrum)

# Godziny prognozy korków na trasie
PREDICTION_HOURS = (3, 4)

# Ile najgorszych korków analizować pod kątem objazdu (limit zapytań API)
MAX_INCIDENT_BYPASSES = 15
MIN_DELAY_FOR_BYPASS_SEC = 45
REFRESH_INTERVAL_SEC = 30

INCIDENT_FIELDS = (
    "{incidents{type,geometry{type,coordinates},properties{"
    "id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},"
    "startTime,endTime,from,to,length,delay,roadNumbers,timeValidity,"
    "probabilityOfOccurrence,numberOfReports,lastReportTime}}}"
)

ICON_CATEGORY_PL = {
    0: "Nieznane",
    1: "Wypadek",
    2: "Mgła",
    3: "Niebezpieczne warunki",
    4: "Deszcz",
    5: "Gołoledź",
    6: "Korek",
    7: "Zamknięty pas",
    8: "Droga zamknięta",
    9: "Roboty drogowe",
    10: "Wiatr",
    11: "Powódź",
    14: "Unieruchomiony pojazd",
}

MAGNITUDE_PL = {
    0: "nieznana",
    1: "niska",
    2: "umiarkowana",
    3: "duża",
    4: "bardzo duża (np. zamknięcie drogi)",
}


def get_traffic_incidents(api_key, bbox, time_validity_filter="present"):
    """Pobiera incydenty drogowe (obecne lub planowane w przyszłości)."""
    url = "https://api.tomtom.com/traffic/services/5/incidentDetails"
    params = {
        "key": api_key,
        "bbox": bbox,
        "fields": INCIDENT_FIELDS,
        "language": "pl-PL",
        "timeValidityFilter": time_validity_filter,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            print(f"TomTom incydenty: błąd {response.status_code}")
            print(response.text)
            return None
        return response.json()
    except requests.exceptions.RequestException as exc:
        print(f"Błąd połączenia (incydenty): {exc}")
        return None


def explain_incident(incident):
    """Buduje wyjaśnienie: dlaczego jest korek / zator w tym miejscu."""
    props = incident.get("properties", {})
    geometry = incident.get("geometry", {})
    cat = props.get("iconCategory", 0)
    category = ICON_CATEGORY_PL.get(cat, f"kategoria {cat}")

    events = props.get("events") or []
    event_texts = [e.get("description", "").strip() for e in events if e.get("description")]
    primary_reason = event_texts[0] if event_texts else category

    road_from = props.get("from") or "?"
    road_to = props.get("to") or "?"
    roads = ", ".join(props.get("roadNumbers") or []) or f"{road_from} → {road_to}"

    delay = props.get("delay") or 0
    length_m = props.get("length") or 0
    magnitude = MAGNITUDE_PL.get(props.get("magnitudeOfDelay", 0), "?")
    time_validity = props.get("timeValidity", "present")
    probability = props.get("probabilityOfOccurrence", "")

    when = "teraz" if time_validity == "present" else "planowane (przyszłość)"
    if props.get("startTime"):
        when += f", od {props['startTime']}"
    if props.get("endTime"):
        when += f" do {props['endTime']}"

    lines = [
        f"<b>Dlaczego tu jest problem?</b><br>",
        f"Przyczyna: <b>{primary_reason}</b> ({category}).<br>",
        f"Lokalizacja: {roads}.<br>",
        f"Opóźnienie: {delay} s, długość: {int(length_m)} m, intensywność: {magnitude}.<br>",
        f"Status: {when}.",
    ]
    if probability:
        lines.append(f"<br>Pewność: {probability}.")
    if len(event_texts) > 1:
        lines.append(f"<br>Szczegóły: {'; '.join(event_texts)}.")

    if geometry.get("type") == "Point":
        lines.append("<br><i>Punktowy incydent — typowo blokuje pas lub wymusza zwalnianie.</i>")
    elif geometry.get("type") == "LineString":
        lines.append("<br><i>Incydent rozciąga się wzdłuż odcinka drogi — tworzy lub wydłuża korek.</i>")

    return "".join(lines)


def format_bypass_popup(bypass):
    """Tekst rekomendacji objazdu do popupu po kliknięciu czerwonej linii."""
    if not bypass or not bypass.get("recommended"):
        return (
            "<br><br><b>Objazd:</b> TomTom nie znalazł wyraźnie lepszej trasy wokół tego miejsca. "
            "Spróbuj poczekać lub wybierz inną trasę ręcznie w nawigacji."
        )

    saved = bypass.get("saved_sec", 0)
    savings = (
        f"Oszczędzisz ~{format_duration(saved)} vs jazda przez ten korek.<br>"
        if saved > 30
        else "Ta trasa omija zator — powinna być płynniejsza.<br>"
    )
    return (
        f"<br><br><b>Rekomendowany objazd</b><br>"
        f"Zamiast przez ten odcinek: jedź <b>{bypass['via']}</b>.<br>"
        f"Czas objazdu: {format_duration(bypass['travel_sec'])}, "
        f"korki: +{format_duration(bypass['delay_sec'])}.<br>"
        f"{savings}"
        f"<i>Na mapie: <span style='color:green;font-weight:bold'>zielona przerywana linia</span> "
        f"= proponowany objazd tego korku.</i>"
    )


def incident_endpoints(incident):
    """Początek i koniec incydentu jako (lat, lon)."""
    geometry = incident.get("geometry", {})
    if geometry.get("type") == "LineString":
        coords = geometry["coordinates"]
        s, e = coords[0], coords[-1]
        return (s[1], s[0]), (e[1], e[0])
    if geometry.get("type") == "Point":
        lon, lat = geometry["coordinates"]
        return (lat, lon), (lat, lon)
    return None, None


def incident_id(incident):
    props = incident.get("properties", {})
    return props.get("id") or str(id(incident))


def route_passes_near(points, center, max_km=0.45):
    """Czy trasa przechodzi blisko punktu (np. środek korku)."""
    if not points or not center:
        return False
    step = max(1, len(points) // 30)
    return min(distance_km(center, pt) for pt in points[::step]) <= max_km


def pick_significant_incidents(incidents, main_route_points, limit=MAX_INCIDENT_BYPASSES):
    """Wybiera korki warte analizy objazdu (największe opóźnienia)."""
    scored = []
    for inc in incidents:
        props = inc.get("properties", {})
        delay = props.get("delay") or 0
        magnitude = props.get("magnitudeOfDelay") or 0
        cat = props.get("iconCategory", 0)
        if delay < MIN_DELAY_FOR_BYPASS_SEC and magnitude < 2 and cat not in (1, 8):
            continue
        if incident_centroid(inc) is None:
            continue
        on_trip = 1 if main_route_points and incidents_near_route([inc], main_route_points, max_km=1.2) else 0
        score = delay + magnitude * 60 + on_trip * 120
        scored.append((score, inc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [inc for _, inc in scored[:limit]]


def compute_bypass_for_incident(api_key, incident, trip_origin, trip_dest, direct_trip_time=None):
    """
    Liczy objazd dla konkretnego korku (czerwonej linii).
    Strategia: alternatywa lokalna A→B oraz objazd trasy Gdańsk→Gdynia wokół punktu.
    """
    props = incident.get("properties", {})
    start, end = incident_endpoints(incident)
    mid = incident_centroid(incident)
    if not start or not mid:
        return {"recommended": False}

    loc_name = props.get("from") or (props.get("roadNumbers") or ["ten odcinek"])[0]
    candidates = []

    start_s = f"{start[0]:.5f},{start[1]:.5f}"
    end_s = f"{end[0]:.5f},{end[1]:.5f}"

    local = calculate_route_locations(api_key, f"{start_s}:{end_s}", max_alternatives=2)
    local_routes = (local or {}).get("routes") or []
    if len(local_routes) >= 2:
        through = local_routes[0]["summary"]
        around = local_routes[1]
        around_sum = around["summary"]
        saved = through.get("travelTimeInSeconds", 0) - around_sum.get("travelTimeInSeconds", 0)
        delay_gain = through.get("trafficDelayInSeconds", 0) - around_sum.get("trafficDelayInSeconds", 0)
        if saved > 20 or delay_gain > 30:
            candidates.append(
                {
                    "route": around,
                    "points": route_points(around),
                    "via": f"bocznymi drogami wokół {loc_name}",
                    "travel_sec": around_sum.get("travelTimeInSeconds", 0),
                    "delay_sec": around_sum.get("trafficDelayInSeconds", 0),
                    "saved_sec": max(saved, 0),
                    "scope": "local",
                }
            )

    detour_dirs = [
        ("północ", 0.012, 0.015),
        ("południe", -0.012, -0.015),
        ("wschód", 0.015, 0.012),
        ("zachód", -0.015, -0.012),
    ]
    for side, dlat, dlon in detour_dirs:
        wp = f"{mid[0] + dlat:.5f},{mid[1] + dlon:.5f}"
        data = calculate_route_locations(api_key, f"{trip_origin}:{wp}:{trip_dest}", max_alternatives=0)
        routes = (data or {}).get("routes") or []
        if not routes:
            continue
        route = routes[0]
        pts = route_points(route)
        if route_passes_near(pts, mid):
            continue
        summary = route["summary"]
        ref_time = direct_trip_time or summary.get("travelTimeInSeconds", 0)
        saved = ref_time - summary.get("travelTimeInSeconds", 0)
        candidates.append(
            {
                "route": route,
                "points": pts,
                "via": f"od strony {side} (omijasz {loc_name})",
                "travel_sec": summary.get("travelTimeInSeconds", 0),
                "delay_sec": summary.get("trafficDelayInSeconds", 0),
                "saved_sec": saved,
                "scope": "trip",
            }
        )

    if not candidates:
        return {"recommended": False}

    best = min(candidates, key=lambda c: (c["delay_sec"], c["travel_sec"]))
    best["recommended"] = True
    best["via_label"] = best["via"]
    return best


def compute_incident_bypasses(api_key, incidents, main_route_points):
    """Pre-liczy objazdy dla najgorszych korków (pokazywane po kliknięciu linii)."""
    targets = pick_significant_incidents(incidents, main_route_points)
    print(f"Analiza objazdów dla {len(targets)} najgorszych korków...")

    direct = calculate_routes(api_key, ROUTE_ORIGIN, ROUTE_DESTINATION, max_alternatives=0)
    direct_time = None
    if direct and direct.get("routes"):
        direct_time = direct["routes"][0]["summary"].get("travelTimeInSeconds")

    bypasses = {}
    for idx, inc in enumerate(targets, start=1):
        iid = incident_id(inc)
        props = inc.get("properties", {})
        loc = props.get("from") or "?"
        bypass = compute_bypass_for_incident(
            api_key, inc, ROUTE_ORIGIN, ROUTE_DESTINATION, direct_time
        )
        bypasses[iid] = bypass
        status = bypass["via"] if bypass.get("recommended") else "brak lepszej trasy"
        line = f"  [{idx}/{len(targets)}] {loc}: {status}"
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode("ascii"))

    return bypasses


def poland_timezone():
    """Strefa czasu Polski (Europe/Warsaw) z fallbackiem bez pakietu tzdata."""
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Europe/Warsaw")
        except Exception:
            pass
    # CEST/CET: przybliżenie bez bazy stref (czerwiec = +2)
    month = datetime.now().month
    offset = 2 if 3 <= month <= 10 else 1
    return timezone(timedelta(hours=offset))


def depart_at_iso(hours_from_now=0):
    """Czas wyjazdu w formacie ISO 8601 (strefa Europe/Warsaw)."""
    dt = datetime.now(poland_timezone()) + timedelta(hours=hours_from_now)
    return dt.isoformat(timespec="seconds")


def calculate_routes(api_key, origin, destination, depart_at="now", max_alternatives=2):
    """Trasa między dwoma punktami (lat,lon)."""
    locations = f"{origin}:{destination}"
    return calculate_route_locations(api_key, locations, depart_at, max_alternatives)


def calculate_route_locations(api_key, locations, depart_at="now", max_alternatives=2):
    """Trasa przez 2+ punktów: 'lat,lon:lat,lon' lub z waypointami."""
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{locations}/json"
    params = {
        "key": api_key,
        "traffic": "true",
        "travelMode": "car",
        "routeType": "fastest",
        "maxAlternatives": max_alternatives,
        "alternativeType": "anyRoute",
        "sectionType": "traffic",
        "computeTravelTimeFor": "all",
        "departAt": depart_at,
        "language": "pl-PL",
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            return None
        return response.json()
    except requests.exceptions.RequestException:
        return None


def route_points(route):
    """Współrzędne trasy jako lista [lat, lon]."""
    points = []
    for leg in route.get("legs", []):
        for pt in leg.get("points", []):
            points.append([pt["latitude"], pt["longitude"]])
    return points


def traffic_sections(route, all_points):
    """Fragmenty trasy objęte korkiem (sekcje TRAFFIC)."""
    sections = []
    for section in route.get("sections", []):
        if section.get("sectionType") != "TRAFFIC":
            continue
        start = section.get("startPointIndex", 0)
        end = section.get("endPointIndex", 0)
        if end >= len(all_points):
            end = len(all_points) - 1
        coords = all_points[start : end + 1]
        if len(coords) < 2:
            continue
        sections.append(
            {
                "coords": coords,
                "delay": section.get("delayInSeconds", 0),
                "speed": section.get("effectiveSpeedInKmh"),
                "category": section.get("simpleCategory", "UNKNOWN"),
                "magnitude": section.get("magnitudeOfDelay", 0),
            }
        )
    return sections


def incident_centroid(incident):
    geometry = incident.get("geometry", {})
    if geometry.get("type") == "Point":
        lon, lat = geometry["coordinates"]
        return lat, lon
    if geometry.get("type") == "LineString":
        coords = geometry["coordinates"]
        mid = coords[len(coords) // 2]
        return mid[1], mid[0]
    return None


def distance_km(a, b):
    """Przybliżona odległość km (Haversine uproszczony dla małych dystansów)."""
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * 0.65
    return (dlat ** 2 + dlon ** 2) ** 0.5


def incidents_near_route(incidents, route_coords, max_km=0.8):
    """Incydenty blisko trasy (prawdopodobna przyczyna korka na tej trasie)."""
    if not route_coords:
        return []
    near = []
    for inc in incidents:
        center = incident_centroid(inc)
        if not center:
            continue
        min_dist = min(distance_km(center, pt) for pt in route_coords[:: max(1, len(route_coords) // 40)])
        if min_dist <= max_km:
            near.append((min_dist, inc))
    near.sort(key=lambda x: x[0])
    return [inc for _, inc in near]


def format_duration(seconds):
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def add_auto_refresh_meta(m, interval=REFRESH_INTERVAL_SEC):
    m.get_root().html.add_child(
        folium.Element(f'<meta http-equiv="refresh" content="{interval}">')
    )


def build_fast_report(api_key):
    present = get_traffic_incidents(api_key, BBOX_TROJMIASTO, "present")
    present_list = (present or {}).get("incidents") or []
    direct = calculate_routes(api_key, ROUTE_ORIGIN, ROUTE_DESTINATION, depart_at="now", max_alternatives=0)
    direct_routes = (direct or {}).get("routes") or []
    return {
        "present_incidents": present_list,
        "future_incidents": [],
        "routes_now": direct_routes,
        "predictions": {},
        "bypass": {
            "recommend_alt": False,
            "text": "Szybki start mapy. Pełne dane i objazdy pojawią się wkrótce.",
        },
        "incident_bypasses": {},
    }


def recommend_bypass(main_route, all_routes, present_incidents):
    """Porównuje trasę główną z alternatywą i sugeruje objazd."""
    if not all_routes:
        return None

    main = all_routes[0]
    main_summary = main.get("summary", {})
    main_points = route_points(main)
    main_near = incidents_near_route(present_incidents, main_points)

    best = main
    best_idx = 0
    main_delay = main_summary.get("trafficDelayInSeconds", 0)
    main_score = main_summary.get("travelTimeInSeconds", 0) + main_delay * 0.4
    best_score = main_score
    for idx, route in enumerate(all_routes[1:], start=1):
        summary = route["summary"]
        score = summary.get("travelTimeInSeconds", 0) + summary.get("trafficDelayInSeconds", 0) * 0.4
        if score < best_score:
            best = route
            best_idx = idx
            best_score = score

    best_delay = best["summary"].get("trafficDelayInSeconds", 0)
    time_saved = main_summary.get("travelTimeInSeconds", 0) - best["summary"].get("travelTimeInSeconds", 0)
    delay_saved = main_delay - best_delay

    causes = []
    for inc in main_near[:3]:
        props = inc.get("properties", {})
        events = props.get("events") or []
        reason = events[0]["description"] if events else ICON_CATEGORY_PL.get(props.get("iconCategory"), "?")
        loc = props.get("from") or props.get("roadNumbers", ["?"])[0] if props.get("roadNumbers") else "?"
        causes.append(f"{reason} ({loc})")

    cause_text = "; ".join(causes) if causes else "typowy szczyt / zator na głównej trasie"

    if best_idx == 0 or (time_saved <= 60 and delay_saved <= 90):
        return {
            "recommend_alt": False,
            "text": (
                f"Trasa główna jest obecnie najlepsza. "
                f"Szacowany czas: {format_duration(main_summary['travelTimeInSeconds'])}, "
                f"korki: +{format_duration(main_delay)}. "
                f"Możliwe przyczyny opóźnień: {cause_text}."
            ),
            "main_route": main,
            "alt_route": None,
        }

    alt_near = incidents_near_route(present_incidents, route_points(best))
    alt_cause = "brak poważnych incydentów w pobliżu" if not alt_near else f"{len(alt_near)} mniejsze zdarzenia"

    return {
        "recommend_alt": True,
        "text": (
            f"Korek na trasie głównej — prawdopodobnie przez: {cause_text}. "
            f"Objazd (trasa alternatywna #{best_idx}): oszczędzisz ~{format_duration(time_saved)}, "
            f"korki na objezdzie: +{format_duration(best_delay)} vs +{format_duration(main_delay)} "
            f"na głównej ({alt_cause})."
        ),
        "main_route": main,
        "alt_route": best,
        "time_saved_sec": time_saved,
    }


def add_incidents_to_map(m, incidents, layer_name, color, dash=None, prefix="", bypasses=None):
    """Rysuje incydenty; po kliknięciu czerwonej linii — przyczyna + rekomendacja objazdu."""
    group = folium.FeatureGroup(name=layer_name, show=True)
    bypass_group = folium.FeatureGroup(name="Objazdy (kliknij korek)", show=True)
    bypasses = bypasses or {}
    count = 0
    bypass_count = 0

    for incident in incidents or []:
        props = incident.get("properties", {})
        geometry = incident.get("geometry", {})
        iid = incident_id(incident)
        bypass = bypasses.get(iid)
        popup_html = explain_incident(incident) + format_bypass_popup(bypass)
        cat = props.get("iconCategory")

        if cat == 1 and geometry.get("type") == "Point":
            lon, lat = geometry["coordinates"]
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup_html, max_width=360),
                tooltip=f"{prefix}Wypadek — kliknij po objazd",
                icon=folium.Icon(color="red", icon="remove-sign"),
            ).add_to(group)
            count += 1
        elif geometry.get("type") == "LineString":
            coords = [(lat, lon) for lon, lat in geometry["coordinates"]]
            loc = props.get("from") or "Korek"
            folium.PolyLine(
                locations=coords,
                color=color,
                weight=6,
                opacity=0.85,
                dash_array=dash,
                popup=folium.Popup(popup_html, max_width=360),
                tooltip=f"{prefix}{loc} — kliknij po objazd",
            ).add_to(group)
            count += 1

            if bypass and bypass.get("recommended") and bypass.get("points"):
                folium.PolyLine(
                    locations=bypass["points"],
                    color="green",
                    weight=5,
                    opacity=0.75,
                    dash_array="10, 8",
                    popup=folium.Popup(
                        f"<b>Objazd: {loc}</b><br>{format_bypass_popup(bypass)}",
                        max_width=360,
                    ),
                    tooltip=f"Objazd wokół {loc}",
                ).add_to(bypass_group)
                bypass_count += 1
        elif geometry.get("type") == "Point":
            lon, lat = geometry["coordinates"]
            folium.CircleMarker(
                location=[lat, lon],
                radius=7,
                color=color,
                fill=True,
                popup=folium.Popup(popup_html, max_width=360),
                tooltip=f"{prefix}Zdarzenie — kliknij",
            ).add_to(group)
            count += 1

    group.add_to(m)
    if bypass_count:
        bypass_group.add_to(m)
    return count, bypass_count


def add_route_to_map(m, route, color, label, weight=5, dash=None):
    """Rysuje trasę i zaznacza odcinki z korkiem."""
    points = route_points(route)
    if len(points) < 2:
        return

    summary = route.get("summary", {})
    delay = summary.get("trafficDelayInSeconds", 0)
    travel = summary.get("travelTimeInSeconds", 0)

    folium.PolyLine(
        points,
        color=color,
        weight=weight,
        opacity=0.9,
        dash_array=dash,
        popup=(
            f"<b>{label}</b><br>"
            f"Czas: {format_duration(travel)}<br>"
            f"Korki: +{format_duration(delay)}"
        ),
    ).add_to(m)

    for section in traffic_sections(route, points):
        folium.PolyLine(
            section["coords"],
            color="darkred",
            weight=weight + 3,
            opacity=0.95,
            popup=(
                f"Korek na trasie<br>"
                f"Opóźnienie: {section['delay']} s<br>"
                f"Prędkość: {section.get('speed', '?')} km/h<br>"
                f"Typ: {section.get('category', '?')}"
            ),
        ).add_to(m)


def build_prediction_report(api_key):
    """Zbiera dane: teraz, +3h, +4h oraz rekomendację objazdu."""
    print("Pobieranie incydentów (teraz)...")
    present = get_traffic_incidents(api_key, BBOX_TROJMIASTO, "present")
    print("Pobieranie incydentów (planowane)...")
    future = get_traffic_incidents(api_key, BBOX_TROJMIASTO, "future")

    present_list = (present or {}).get("incidents") or []
    future_list = (future or {}).get("incidents") or []
    print(f"Incydenty teraz: {len(present_list)}, planowane: {len(future_list)}")

    print("Obliczanie trasy i objazdów (teraz)...")
    routes_now = calculate_routes(api_key, ROUTE_ORIGIN, ROUTE_DESTINATION, depart_at="now")
    route_list_now = (routes_now or {}).get("routes") or []

    predictions = {}
    for hours in PREDICTION_HOURS:
        depart = depart_at_iso(hours)
        print(f"Prognoza trasy za {hours} h (wyjazd o {depart})...")
        data = calculate_routes(api_key, ROUTE_ORIGIN, ROUTE_DESTINATION, depart_at=depart)
        routes = (data or {}).get("routes") or []
        if routes:
            s = routes[0]["summary"]
            predictions[hours] = {
                "depart_at": depart,
                "travel_sec": s.get("travelTimeInSeconds", 0),
                "delay_sec": s.get("trafficDelayInSeconds", 0),
                "route": routes[0],
            }
            print(
                f"  Za {hours} h: czas {format_duration(s['travelTimeInSeconds'])}, "
                f"korki +{format_duration(s.get('trafficDelayInSeconds', 0))}"
            )

    bypass = recommend_bypass(
        route_list_now[0] if route_list_now else None,
        route_list_now,
        present_list,
    )

    main_points = route_points(route_list_now[0]) if route_list_now else []
    incident_bypasses = compute_incident_bypasses(api_key, present_list, main_points)

    return {
        "present_incidents": present_list,
        "future_incidents": future_list,
        "routes_now": route_list_now,
        "predictions": predictions,
        "bypass": bypass,
        "incident_bypasses": incident_bypasses,
    }


def visualize_prediction_map(report, quick=False):
    """Mapa: incydenty, prognoza +3/+4 h, trasa główna vs objazd."""
    m = folium.Map(location=[54.45, 18.55], zoom_start=11)
    add_auto_refresh_meta(m)
    last_updated = datetime.now(poland_timezone()).strftime("%Y-%m-%d %H:%M:%S")

    n_now, n_bypass = add_incidents_to_map(
        m,
        report["present_incidents"],
        "Korki TERAZ",
        "red",
        prefix="[Teraz] ",
        bypasses=report.get("incident_bypasses"),
    )
    n_future, _ = add_incidents_to_map(
        m,
        report["future_incidents"],
        "Incydenty PLANOWANE (przyszłość)",
        "purple",
        dash="10, 10",
        prefix="[Plan] ",
    )

    if report["routes_now"]:
        add_route_to_map(m, report["routes_now"][0], "blue", "Trasa główna (teraz)")

    bypass = report.get("bypass") or {}
    if bypass.get("recommend_alt") and bypass.get("alt_route"):
        add_route_to_map(m, bypass["main_route"], "gray", "Trasa główna (z korkiem)", weight=4, dash="5, 8")
        add_route_to_map(m, bypass["alt_route"], "green", "Rekomendowany objazd", weight=6)

    pred_colors = {3: "orange", 4: "darkorange"}
    for hours, pred in report.get("predictions", {}).items():
        add_route_to_map(
            m,
            pred["route"],
            pred_colors.get(hours, "orange"),
            f"Prognoza trasy za {hours} h",
            weight=4,
            dash="8, 6",
        )

    folium.LayerControl(collapsed=False).add_to(m)

    bypass_text = bypass.get("text", "Brak danych o trasie.")
    pred_lines = []
    for h, p in sorted(report.get("predictions", {}).items()):
        pred_lines.append(
            f"Za {h} h: {format_duration(p['travel_sec'])} "
            f"(+{format_duration(p['delay_sec'])} korki)"
        )
    pred_block = "<br>".join(pred_lines) if pred_lines else "Brak prognozy trasy."

    quick_note = "<br><em>Szybki start mapy. Pełne dane i objazdy pojawią się wkrótce.</em>" if quick else ""
    legend = f"""
    <div style="position:fixed;bottom:30px;left:10px;z-index:9999;background:white;
                padding:12px;border:2px solid #333;border-radius:8px;max-width:420px;font-size:13px;">
        <b>Traffic Intelligence — Trójmiasto</b><br><br>
        <b>Ostatnia aktualizacja:</b> {last_updated}<br>
        <b>Incydenty:</b> teraz {n_now}, planowane {n_future}, objazdy {n_bypass}<br>
        <b>Prognoza trasy Gdańsk→Gdynia:</b><br>{pred_block}<br><br>
        <b>Objazd (cała trasa):</b> {bypass_text}<br><br>
        <i>Kliknij <b>czerwoną linię</b> korku — zobaczysz przyczynę i rekomendowany objazd.</i><br>
        <i>Zielona przerywana linia = objazd wokół wybranego korku.</i>{quick_note}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))

    output_file = "live_traffic_map.html"
    m.save(output_file)
    print(f"\nMapa zapisana: {output_file}")

    report_file = "traffic_report.txt"
    with open(report_file, "w", encoding="utf-8") as fh:
        fh.write("=== RAPORT TRAFFIC ===\n\n")
        fh.write(f"Incydenty teraz: {len(report['present_incidents'])}\n")
        fh.write(f"Incydenty planowane: {len(report['future_incidents'])}\n\n")
        fh.write("PROGNOZA TRASY (Gdańsk → Gdynia):\n")
        for h, p in sorted(report.get("predictions", {}).items()):
            fh.write(
                f"  Za {h} h ({p['depart_at']}): "
                f"{format_duration(p['travel_sec'])}, korki +{format_duration(p['delay_sec'])}\n"
            )
        fh.write(f"\nOBJAZD:\n{bypass_text}\n\n")
        fh.write("PRZYCZYNY KORKÓW (teraz):\n")
        for inc in report["present_incidents"][:15]:
            props = inc.get("properties", {})
            loc = props.get("from") or "?"
            events = props.get("events") or []
            reason = events[0]["description"] if events else ICON_CATEGORY_PL.get(props.get("iconCategory"), "?")
            fh.write(f"  - {loc}: {reason} (+{props.get('delay') or 0} s)\n")
    print(f"Raport tekstowy: {report_file}")


def run_refresh_loop(api_key):
    print("Tworzę szybką startową wersję mapy...")
    quick_report = build_fast_report(api_key)
    visualize_prediction_map(quick_report, quick=True)
    print(f"Mapa została zapisana. Odświeżam dane co {REFRESH_INTERVAL_SEC} sekund.")

    try:
        while True:
            start = time.time()
            report = build_prediction_report(api_key)
            visualize_prediction_map(report)
            elapsed = time.time() - start
            wait = max(REFRESH_INTERVAL_SEC - elapsed, 0)
            print(f"Odświeżanie zakończone. Kolejna aktualizacja za {int(wait)} s.")
            time.sleep(wait)
    except KeyboardInterrupt:
        print("Zatrzymano odświeżanie na życzenie użytkownika.")


if __name__ == "__main__":
    if not TOMTOM_API_KEY or TOMTOM_API_KEY == "TUTAJ_WKLEJ_SWOJ_KLUCZ":
        print("BŁĄD: Ustaw TOMTOM_API_KEY w kodzie.")
    else:
        run_refresh_loop(TOMTOM_API_KEY)
