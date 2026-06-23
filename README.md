# Port-AI

**Żywy układ nerwowy portu** — dashboard operacyjny dla operatorów i spedycji: mapa kongestii, anomalie korytarzowe, prognoza opóźnień (trend + ML), raporty operacyjne oraz automatyczny dispatch slotów bramowych.

Obsługiwane porty: **Gdynia**, **Gdańsk**, **Szczecin**, **Świnoujście**.

> Szczegółowa ścieżka demo na hackathon (~3 min): [`port-ai/DEMO.md`](port-ai/DEMO.md)

---

## Spis treści

- [Tech stack](#tech-stack)
- [Architektura](#architektura)
- [Zewnętrzne API i źródła danych](#zewnętrzne-api-i-źródła-danych)
- [Funkcjonalności](#funkcjonalności)
- [Uruchomienie lokalne](#uruchomienie-lokalne)
- [Zmienne środowiskowe](#zmienne-środowiskowe)
- [Struktura repozytorium](#struktura-repozytorium)
- [API backendu](#api-backendu)
- [Machine Learning](#machine-learning)
- [Rozwiązywanie problemów](#rozwiązywanie-problemów)

---

## Tech stack

| Warstwa | Technologie |
|---------|-------------|
| **Frontend** | React 19, TypeScript, Vite 8, Leaflet / react-leaflet, leaflet.heat, i18next (PL/EN) |
| **Backend** | Python 3.12, FastAPI, Uvicorn, httpx |
| **Strumieniowanie** | Apache Kafka (Redpanda w Dockerze), aiokafka |
| **Baza danych** | Supabase (PostgreSQL) w chmurze; SQLite lokalnie (obserwacje, PCS, fallback) |
| **ML** | scikit-learn (Random Forest), joblib, pandas |
| **Auth** | JWT (python-jose), bcrypt |
| **Voice dispatch** | Twilio + opcjonalnie ElevenLabs Conversational AI |
| **Mapy** | OpenStreetMap (kafelki), TomTom Traffic API (incydenty, heatmapa, flow tiles) |
| **Infra** | Docker Compose (Redpanda), Supabase SQL (`port-ai/supabase/schema.sql`) |

---

## Architektura

```
┌─────────────────┐     /api proxy      ┌──────────────────────────────────┐
│  React (Vite)   │ ◄──────────────────►│  FastAPI (:8001)                 │
│  :5173          │                     │  • agregacja map-data            │
└─────────────────┘                     │  • engine (anomalie, prognoza)   │
                                        │  • TMS / slot dispatch           │
                                        └──────────┬───────────────────────┘
                                                   │
         ┌─────────────────────────────────────────┼─────────────────────────┐
         ▼                     ▼                   ▼                         ▼
   TomTom Traffic API    ZTM / miejskie API   Kafka (Redpanda)        Supabase / SQLite
   (primary)             (context)            bufor prognoz 10–30 min   obserwacje, auth, TMS
         │                     │                   │
         └─────────────► Korytarze geofence (corridors.json) ◄── PCS Excel (CODECO, PortCalls)
```

**Primary vs context:** warstwa *primary* (TomTom) pokazuje korek na drogach publicznych wokół portu. Warstwa *context* (ZTM) pokazuje ruch miejski (autobusy, pętle, pojazdy) — pomaga odróżnić korek zewnętrzny od szczytu planowego przy bramie.

---

## Zewnętrzne API i źródła danych

### TomTom (primary — wszystkie porty)

| Usługa | Endpoint / zastosowanie |
|--------|-------------------------|
| **Traffic Incidents** | Incydenty drogowe, opóźnienia, geometria odcinków |
| **Flow tiles** | Kafelki przepływu na mapie (`/api/v1/tomtom/tiles/flow/...`) |
| **Heatmapa** | Agregacja punktów intensywności z incydentów |

Wymaga klucza: `TOMTOM_API_KEY` w `port-ai/backend/.env`.

### API miejskie (context — ZTM)

| Port | API | Co pobieramy |
|------|-----|--------------|
| **Gdynia** | `https://api.zdiz.gdynia.pl/ri/rest/traffic_intensities` | Intensywność na pętlach indukcyjnych (~5 min) |
| **Gdynia** | `https://api.zdiz.gdynia.pl/ri/rest/road_segments` | Geometria odcinków |
| **Gdańsk** | `https://ckan2.multimediagdansk.pl/gpsPositions?v=2` | Pozycje GPS autobusów ZTM (~20 s) |
| **Szczecin** | `https://zditm.szczecin.pl/api/v1/vehicles` | Pojazdy ZDiTM (~10 s) |
| **Świnoujście** | — | Brak publicznego feedu ZTM; tylko TomTom + zdefiniowane korytarze (S3, tunel, prom) |

### Dane portowe (PCS)

Eksporty Excel (CODECO, PortCalls, DspShips) ładowane do SQLite przez `port_data_loader.py`:

- popyt bramowy / kontenerowy per terminal,
- werdykt **TomTom vs popyt CODECO** (anomalie popytu),
- panel **Operacje portowe** w sidebarze.

Pliki: `port-ai/backend/data/port/raw/*.xlsx` (lub `PORT_DATA_DIR`).

### Opcjonalne integracje

| Usługa | Cel |
|--------|-----|
| **Supabase Postgres** | Obserwacje korytarzowe, użytkownicy, TMS w chmurze |
| **Twilio** | Połączenia głosowe do spedycji przy dispatch |
| **ElevenLabs** | Agent głosowy (alternatywa dla Twilio `<Say>`) |

---

## Funkcjonalności

### Mapa live (`Live`)

- Heatmapa TomTom + kafelki flow + incydenty jako segmenty z popupami.
- Korytarze dostępowe (geofence) per port — kliknięcie wybiera korytarz.
- Badge źródeł danych w pasku statusu (TomTom / ZTM / PCS).
- **Popup raportu operacyjnego** na korytarzu: *co się dzieje / dlaczego / rekomendacja* + kopiowanie raportu do schowka.

### Silnik anomalii i wąskie gardła

- **`GET /api/v1/engine/events`** — zdarzenia korytarzowe (severity, opóźnienie, trend).
- **`GET /api/v1/anomalies`** — werdykt **ANOMALY / WATCH / NORMAL**: czy korek TomTom koreluje z popytem bramowym (CODECO).
- **`GET /api/v1/engine/bottlenecks`** — ranking korytarzy z największym opóźnieniem (okno 60 min).

### Prognoza hybrydowa (`Predykcja`)

| Horyzont | Metoda | Opis |
|----------|--------|------|
| **10–30 min** | `kafka_trend` | Ekstrapolacja trendu z bufora Kafka (live) |
| fallback | `observation_trend` | Trend z historii obserwacji SQLite/Postgres |
| **45–180 min** | `ml_live` / `ml_blend` | Random Forest z kontekstem bieżącego opóźnienia + profil dobowy |

Próg alertu dispatch w UI: **≥ 600 s** (10 min).

### TMS i slot dispatch

- Mock armator **MSC** — sloty bramowe, spedycje, bookingi.
- **`slot_dispatch_service`** — gdy prognoza ≥ `SLOT_DISPATCH_MIN_DELAY_SEC`, plan alertu i opcjonalne połączenie głosowe.
- Historia połączeń: `GET /api/v1/tms/dispatch/history`.

### Narzędzia demo (nagłówek)

| Przycisk | Co robi | Wpływ na dane |
|----------|---------|---------------|
| **Wizualizacja tłumu** | Syntetyczna heatmapa + 6 incydentów wzdłuż korytarza (120→960 s) | Tylko warstwa mapy — **bez** prognoz i dispatch |
| **Symulator incydentu (spike)** | Wstrzykuje rosnące opóźnienia do Kafka + DB, tworzy slot TMS, przelicza prognozy, uruchamia dispatch | **Pełna pętla operacyjna**; domyślnie `dry_run` (bez dzwonienia) |
| **Edytor korytarzy** | Rysowanie geofence, zapis do API | Dev — zmienia przypisanie zdarzeń do korytarzy |

Długie opisy narzędzi demo: panel boczny → sekcja **„Narzędzia demo i kalibracji”**.

### Auth

- Rejestracja / logowanie operatorów (`JWT_SECRET`).
- Frontend: `http://localhost:5173/#/login`

### i18n

- Interfejs PL / EN (przełącznik w nagłówku).

---

## Uruchomienie lokalne

### Wymagania

- Python 3.11+
- Node.js 20+
- Docker (opcjonalnie, dla Kafka)
- Klucz **TomTom API**

### 1. Backend

```powershell
cd port-ai\backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# Uzupełnij TOMTOM_API_KEY, opcjonalnie DATABASE_URL i JWT_SECRET
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Sprawdzenie: [http://127.0.0.1:8001/health](http://127.0.0.1:8001/health) → `"status": "ok"`

### 2. Frontend

```powershell
cd port-ai\frontend
npm install
npm run dev
```

Dashboard: [http://localhost:5173/](http://localhost:5173/) — proxy `/api` → backend `:8001`.

### 3. Kafka (opcjonalnie — prognoza `kafka_trend`)

```powershell
cd port-ai
docker compose up -d
```

Broker: `localhost:8081`, temat: `port-traffic-events`.

### 4. Konto demo

1. Ustaw `JWT_SECRET` w `.env`.
2. Otwórz [http://localhost:5173/#/login](http://localhost:5173/#/login).
3. Zarejestruj konto testowe (np. `demo@port-ai.pl`).

### 5. Supabase (opcjonalnie)

1. Utwórz projekt Supabase.
2. Uruchom SQL z [`port-ai/supabase/schema.sql`](port-ai/supabase/schema.sql).
3. Ustaw `DATABASE_URL` w `.env`.

Bez `DATABASE_URL` backend używa **SQLite** lokalnie (`corridor_observations.db`).

---

## Zmienne środowiskowe

Skopiuj `port-ai/backend/.env.example` → `.env`.

| Zmienna | Wymagane | Opis |
|---------|----------|------|
| `TOMTOM_API_KEY` | **tak** (prod) | Incydenty, heatmapa, flow tiles |
| `JWT_SECRET` | zalecane | Auth operatorów |
| `DATABASE_URL` | opcjonalnie | Supabase Postgres; bez niego SQLite |
| `KAFKA_BOOTSTRAP_SERVERS` | opcjonalnie | `localhost:8081` |
| `TRAFFIC_ML_ENABLED` | opcjonalnie | `true` — model RF |
| `TRAFFIC_ML_MODEL_PATH` | opcjonalnie | Ścieżka do `.pkl` |
| `SLOT_DISPATCH_MIN_DELAY_SEC` | opcjonalnie | Próg alertu (domyślnie `600`) |
| `TWILIO_*`, `ELEVENLABS_*` | opcjonalnie | Voice dispatch |
| `PORT_DATA_DIR` | opcjonalnie | Katalog z plikami PCS `.xlsx` |

**Uwaga:** nie commituj pliku `.env` z prawdziwymi kluczami.

---

## Struktura repozytorium

```
Hakaton/
├── README.md                 ← ten plik
├── port-ai/
│   ├── DEMO.md               ← scenariusz prezentacji hackathon
│   ├── docker-compose.yml    ← Redpanda (Kafka)
│   ├── supabase/             ← schema SQL
│   ├── backend/
│   │   ├── main.py           ← FastAPI, agregacja API
│   │   ├── hybrid_delay_forecaster.py
│   │   ├── traffic_ml_predictor.py
│   │   ├── slot_dispatch_service.py
│   │   ├── observation_store.py
│   │   ├── data/ml/          ← model RF + backtest_report.json
│   │   └── ml/               ← trening, backtest
│   └── frontend/
│       └── src/              ← React dashboard
└── ZTM Gdynia+Gdańsk+Szczecin/   ← wczesny prototyp / referencja (legacy)
```

---

## API backendu

| Metoda | Endpoint | Opis |
|--------|----------|------|
| GET | `/health` | Status serwisu, ML, Kafka, auth |
| GET | `/api/v1/map-data` | Mapa: primary + context + heatmapa + prognozy + PCS |
| GET | `/api/v1/engine/events` | Zdarzenia / anomalie korytarzowe |
| GET | `/api/v1/engine/bottlenecks` | Wąskie gardła (60 min) |
| GET | `/api/v1/engine/forecast` | Prognoza hybrydowa per korytarz |
| GET | `/api/v1/engine/corridors` | Snapshoty korytarzy |
| GET | `/api/v1/anomalies` | TomTom vs popyt CODECO |
| GET | `/api/v1/tms/snapshot` | Sloty i spedycje TMS |
| POST | `/api/v1/tms/dispatch/run` | Ręczny dispatch |
| GET | `/api/v1/demo/crowd-map` | Syntetyczny tłum (demo mapy) |
| POST | `/api/v1/demo/corridor-spike` | Spike opóźnień + dispatch (dry-run domyślnie) |
| POST | `/api/v1/auth/register` | Rejestracja |
| POST | `/api/v1/auth/login` | Logowanie |

Pełna dokumentacja interaktywna: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs) (Swagger UI).

---

## Machine Learning

- **Model:** Random Forest (`data/ml/traffic_delay_regressor.pkl`).
- **Cechy v2:** lokalizacja, godzina, dzień tygodnia, bieżące opóźnienie, slope trendu, kod korytarza.
- **Krótki horyzont (10–30 min):** trend z bufora — ML go nie zastępuje.
- **Długi horyzont (45–180 min):** profil historyczny + kontekst live.

### Trening z obserwacji

```powershell
cd port-ai\backend
.\.venv\Scripts\python.exe ml\train_from_observations.py --sqlite
```

### Backtest

```powershell
.\.venv\Scripts\python.exe ml\backtest_forecast.py --history-only --sqlite
```

Raport: `port-ai/backend/data/ml/backtest_report.json`

---

## Rozwiązywanie problemów

| Problem | Rozwiązanie |
|---------|-------------|
| TomTom 403 / brak incydentów | Sprawdź `TOMTOM_API_KEY`, zrestartuj backend |
| `404` na `/demo/crowd-map` | Stary proces uvicorn — restart backendu |
| Brak `kafka_trend` | Uruchom `docker compose up -d`, poczekaj na zapełnienie bufora |
| Login blokuje dostęp | Zarejestruj konto lub ustaw `JWT_SECRET` |
| Supabase „max clients” | Backtest z `--sqlite`; lokalnie usuń `DATABASE_URL` |
| Port 8001 zajęty | Windows: `Get-NetTCPConnection -LocalPort 8001` → zakończ proces |

---

## Licencja i zespół

Projekt hackathonowy — **Wyzwanie 3: Żywy układ nerwowy portu**.

W repozytorium znajduje się też folder `ZTM Gdynia+Gdańsk+Szczecin/` — wczesna wersja integracji ZTM + TomTom; **produkcyjny dashboard to `port-ai/`**.
