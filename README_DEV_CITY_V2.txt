InfluRank DEV — City + pagination v2

Wrzucaj tę paczkę na branch: dev

Zmieniane pliki:
  apps/web/index.html
  apps/web/app.js
  apps/web/styles.css

UWAGA:
Paczka celowo NIE zawiera apps/web/data/creators.json.
Dzięki temu nie nadpisuje danych. Autopilot może dalej synchronizować
najnowszy creators.json z main → dev.

Co nowego:
- kolumna Miasto w rankingu,
- filtr po mieście,
- wyszukiwarka znajduje też miasta,
- GEO w drawerze twórcy:
    * powiązane miasto,
    * miasto z bio,
    * confidence,
    * inne miasta contentu,
- statystyka coverage GEO,
- paginacja zamiast jednej bardzo długiej listy,
- domyślnie 100 twórców na stronę,
- wybór: 50 / 100 / 250 / 500 na stronę,
- filtrowanie i wyszukiwanie nadal działa na całej wczytanej bazie.

Po commicie do dev Netlify powinien automatycznie odświeżyć:
  dev--rankinginflu.netlify.app
