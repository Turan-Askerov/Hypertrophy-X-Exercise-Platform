# Teknik Referanslar

## Render Blueprint ve PostgreSQL

Projedeki kök `render.yaml` manifesti, Render'ın resmî Blueprint referansındaki `databases` tanımı ile uygulama environment variable'ına `fromDatabase.name` ve `fromDatabase.property: connectionString` üzerinden PostgreSQL bağlantısı aktarma yapısını izler.

- Render Blueprint YAML Reference: <https://render.com/docs/blueprint-spec>
