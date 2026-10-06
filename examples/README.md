# 範例場景

每個檔案都是 spec §4 格式的場景 JSON，可直接 `castplane render examples/<名稱>.json -o out`。全部使用 36×24 mm 片幅、273×182 mm 畫布（3:2，見 docs/DECISIONS.md 關於 257×182 的說明）。

| 檔案 | 內容 |
| --- | --- |
| `basic.json` | spec §4 的範例場景：旋轉 30° 的木箱與一根圓柱，點光源，略為俯視的相機（畫布改為 273×182 以符合片幅長寬比）。 |
| `construction_demo.json` | 兩個方塊加一個三角稜柱、點光源、廣角相機：作圖線（L′P′、F′Q′、P′Q′）最清楚的示範，README 的插圖即由此渲染。 |
| `curved_demo.json` | 圓柱、球、圓錐三種曲面基元在點光源下：切線母線、明暗交界線、橢圓影子與相機輪廓線。 |
| `three_point.json` | 高塔、木箱與稜柱，相機由高處俯視：三點透視，垂直邊匯聚到第三消失點 VPz。 |
| `directional.json` | 柱、木箱、球、圓錐在平行光（太陽）下，相機以 yaw/pitch 形式給定：F′ 落在地平線上，L′ 在地平線上方。 |
