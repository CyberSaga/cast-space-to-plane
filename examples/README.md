# 範例場景

每個檔案都是 spec §4 格式的場景 JSON，可直接 `castplane render examples/<名稱>.json -o out`。除了 `miki.json` 與 `reiya.json`（兩個角色範例，直式，見表末兩列）以外，全部使用 36×24 mm 片幅、273×182 mm 畫布（3:2，見 docs/DECISIONS.md 關於 257×182 的說明）。

| 檔案 | 內容 |
| --- | --- |
| `basic.json` | spec §4 的範例場景：旋轉 30° 的木箱與一根圓柱，點光源，略為俯視的相機（畫布改為 273×182 以符合片幅長寬比）。 |
| `construction_demo.json` | 兩個方塊加一個三角稜柱、點光源、廣角相機：作圖線（L′P′、F′Q′、P′Q′）最清楚的示範，README 的插圖即由此渲染。 |
| `curved_demo.json` | 圓柱、球、圓錐三種曲面基元在點光源下：切線母線、明暗交界線、橢圓影子與相機輪廓線。 |
| `three_point.json` | 高塔、木箱與稜柱，相機由高處俯視：三點透視，垂直邊匯聚到第三消失點 VPz。 |
| `directional.json` | 柱、木箱、球、圓錐在平行光（太陽）下，相機以 yaw/pitch 形式給定：F′ 落在地平線上。此例的太陽在觀者**後方**（方向的 y 分量為負、相機朝 +Y），所以 L′ 是地平線**下方**的反光點（規格 §5.7 第 1 列），紅色 L′P′ 線從畫面左下方的 L′ 往上拉；平行光不發 `LIGHT_BEHIND_CAMERA`（合約 §2.7、D19）。 |
| `wall_and_ground.json` | M4：無界地面加一面有界牆（y = 6、x ∈ [−3, 3]、高 2.5 m，法線朝 −y 也就是朝光源與相機），點光源下的 1 m 木箱（合約 §5.1.11 的手算驗收場景，`output.hidden_lines` 開啟）。木箱影子在地面上往牆延伸，到牆根 (±3/4, 6, 0) **轉折**爬上牆面，成為牆上高 1/3 m 的四邊形；牆本身也在地面上投出一大片影子（在牆後，畫面上是牆底邊以上的灰帶，填色不消隱，輪廓在牆後的部分畫成虛線）。木箱的五條背面邊、被木箱擋住的牆底邊中段（x ∈ (−0.7, 0.7)）與牆上的影子四邊形都畫成虛線，在 `*.hidden` 子群組；`--hidden-style omit` 讓它們消失、`--no-hidden-lines` 回到全部實線。作圖線另有牆面的陰影消失點 `F′wall`（畫面上方），木箱頂點的 F′Q′ 線從它出發。 |
| `mesh_demo.json` | M5 網格匯入：房子從 `meshes/house.obj` 讀入（方塊屋身加山牆屋頂，7 個面，兩面山牆是五邊形），旁邊一個圓柱，點光源在左前上方。`mesh` 物件只寫 `path`，路徑相對於場景檔所在目錄，`render` / `validate` / `info` / `stages` 會先展開成內嵌的 `data` 再驗證（`castplane.io.load_expanded_scene`）；共面合併後的面與參數化多面體一樣有作圖線與自我驗證。 |
| `two_lights.json` | M6 多光源：木箱、圓柱、球在兩盞點光源 `left` (−2, 9.5, 3.6) / `right` (2.8, 10, 3.2) 下，兩盞光都在物件後上方、在畫面內，所以畫面上有兩個 L′（`L.left`、`L.right`）與兩個 F′，紅色 L′P′ 線從兩點各自放射。每個物件投出兩個影子：各光源的影子在 `cast_shadow.left` / `cast_shadow.right` 以 `fill-opacity="0.15"` 畫（一半的色調，只被一盞光遮住的半影因此較淡），兩者重疊的**本影**以 `cast_shadow.umbra` 的一個深色路徑疊在最上面（118 塊凸片）：木箱底下兩個影子交疊的楔形、球底下兩個橢圓影子的交集，還有不同物件之間的交疊（右燈下圓柱的影子壓到左燈下木箱的影子）。木箱被兩盞光都背光的三個面在 `form_shadow.core`（原本的 0.18 色調），只被左燈背光的那一面在 `form_shadow.left`（0.09）；圓柱與球每盞光各有一條明暗交界線。作圖點名稱帶光源 id（`ball.sil.0.left`、`pillar.g0.base.right`）。無警告。 |
| `miki.json` | 花菱美希（《ハヤテのごとく!》）的角色參考模型，給畫畫練習用：1.51 m 的動漫女學生（5.9 頭身），放鬆的 A 字站姿，站在原點的地面上、面向 −Y。**這是兩個直式範例之一**（另一個是 `reiya.json`）：片幅 24×36 mm、畫布 182×273 mm（2:3），是本檔開頭那句話的例外；相機在 (1.7, −3.4, 1.25)、焦距 65 mm，場景給的是一盞太陽（平行光，方向 (−0.335, −0.409, 0.849)）。共 18 個 `mesh` 物件，每個都是內嵌 `data` 的一組空間上緊湊的封閉殼（共 58 個零件殼）：`headband`、`hair`、`head`、`eyes`、`scarf`、`sidelocks`、`blouse`、`collar`、`back_hair`、`arm_l`、`face_marks`、`arm_r`、`legs`、`socks`、`skirt`、`shoes`、`ring`、`neck`（分成 18 個是為了讓消隱快；4181 個頂點、4469 個多邊形、8154 個三角形）。預設圖層是 `objects` 與 `cast_shadow`，`output.hidden_lines` 開啟且 `hidden_style` 為 `omit`，所以被擋住的線不畫（線稿而不是虛線的透視圖）。無警告（`warnings` 為空）。每個物件另有選用的 `display_color`（`"#rrggbb"`，取該物件的主要材質色，如頭髮 `#b9c3e6`、上衣 `#e8667a`），只給網頁的 3D 畫面上色，核心與 SVG / JSON 完全忽略它（D81）。 |
| `reiya.json` | Reiya（レイヤ）的角色參考模型，給畫畫練習用：1.52 m（赤腳，腳底到頭頂）的動漫女孩（7.4 頭身，算到髮冠；穿著樂福鞋時頭頂 1.554 m、髮冠 1.570 m、耳朵形髮束的尖端 1.578 m，是整個模型的最高點），鮭魚粉色的鮑伯頭、頭頂兩個耳朵形的髮束與兩條細辮子，白色立領上衣、海軍藍背心裙（長長的荷葉 A 字裙）、穿在肩下的鏽褐色短版開襟外套（圓鼓鼓的燈籠袖，袖口收成長長的羅紋）、白襪與棕色樂福鞋，左眼藍、右眼紅；皮膚是帶玫瑰色的暖色（`#fad8cd`），鮑伯頭是平滑的鐘形，髮尾是依設計稿分層的細長髮絡，末端是葉形；放鬆的 A 字站姿，手指微微彎曲、手臂靠近身體並有一點手肘彎度，站在原點的地面上、面向 −Y。**這是第二個直式範例**：片幅 24×36 mm、畫布 182×273 mm（2:3），是本檔開頭那句話的例外；相機在 (1.7595, −3.4505, 1.3685)、看向 (0.2932, 0.1466, 0.782)、焦距 65 mm，場景給的是一盞太陽（平行光，方向 (−0.335, −0.409, 0.849)，與 `miki` 相同）。共 27 個 `mesh` 物件，每個都是內嵌 `data` 的一組空間上緊湊的封閉殼（共 115 個零件、123 個封閉殼）：`tufts`、`cardigan`、`arm_l`、`arm_r`、`face_marks_l`、`face_marks_r`、`eye_l`、`eye_r`、`fringe`、`neck`、`bob_l`、`bob_r`、`bob`、`hair`、`head`、`braid_l`、`braid_r`、`hair_under`、`top`、`bodice`、`buttons`、`skirt`、`shoe_l`、`shoe_r`、`sock_l`、`sock_r`、`legs`（分成 27 個是為了讓消隱快，鮑伯頭沿背後兩條外側髮絡線切成 `bob_l`、`bob`、`bob_r` 三個殼也是；5530 個頂點、6354 個多邊形、10576 個三角形）。預設圖層是 `objects` 與 `cast_shadow`，`output.hidden_lines` 開啟且 `hidden_style` 為 `omit`，所以被擋住的線不畫（線稿而不是虛線的透視圖）。無警告（`warnings` 為空）。每個物件另有選用的 `display_color`（`"#rrggbb"`，取該物件的主要材質色，如頭髮 `#f2b5a7`、外套 `#a66b63`、背心裙 `#184059`），只給網頁的 3D 畫面上色，核心與 SVG / JSON 完全忽略它（D81）。 |

## `miki.json` 的用法

> **著作權聲明：** 花菱美希（《ハヤテのごとく!》）的著作權屬於原作的權利人。`miki` 範例與相關檔案是非官方的同人畫畫參考模型，**該角色及其模型不在本專案的授權散布與傳播範圍內**（GPL-3.0 只涵蓋 castplane 軟體）。完整聲明見 [`COPYRIGHT_NOTICE.md`](../COPYRIGHT_NOTICE.md)。

**網頁。** 在 Example 選單選 `miki`，3D 畫面與旁觀視角窗格會用各物件的 `display_color` 上色（頭髮薰衣草藍、上衣紅、圍巾黃、領子白、裙子粉、鞋子棕）。幾個要注意的地方：

- 取消勾選 **labels** 圖層：網格的每個頂點都有標籤，開著會把畫面蓋滿。
- 旁觀視角窗格的「視線」勾選框（預設開啟）會畫出從眼睛到第一個物件——髮箍「headband」——每個頂點的視線（以及它的光線），可以看出髮箍在透視中的位置；取消勾選就能看到不被遮擋的整個人物。
- **form_shadow** 與 **cast_shadow** 的填色**不做消隱**（只有線會依 `hidden_lines` 切成可見與隱藏），所以背光的頭髮會透出來；cast_shadow 是每個物件各畫一個半透明的填色加輪廓，物件重疊的地方（頭、頭髮、髮箍與臉上的零件；手臂與裙子）會疊得更深、也看得到內側的輪廓，練習時描外輪廓即可。cast_shadow 也不被腿與鞋子擋住。
- 要看她的側面、背面或俯仰，拖旁觀視角窗格裡的**橘色圓環**環繞（5° 吸附，按住 Alt 暫停）；「前」按鈕是沿 +y 看她的臉。焦距滑桿改視野。載入或放開滑鼠後的靜止影格（含消隱）約 1.4 秒；拖曳時不做消隱（每格約 40 ms），放開後才補上消隱後的線稿。
- 網頁的「Download scene (current camera)」對網格場景寫出的檔案，`castplane validate` / `render` 可以直接吃（面的索引寫成整數，見合約 §5.4 實作註記），並重現網頁上同一張 SVG；`display_color` 也會寫回。

**命令列。**

```sh
castplane render examples/miki.json -o out              # out/miki.svg 與 out/miki.json（約 4 秒；消隱開啟）
castplane render examples/miki.json -o out --formats svg,png --layers objects,cast_shadow --dpi 150
castplane info examples/miki.json                       # 地平線、消失點與警告表（警告為空）
```

**其他 3D 軟體與匯入。** `meshes/miki.obj`（加 `miki.mtl`：13 種材質，58 個零件各用其一，`display_color` 就是每個物件的主要材質色）與 `meshes/miki.glb`（18 個節點）是同一個模型，給 Blender 等軟體用。`castplane import` 讀 GLB 時一個節點變成一個 `mesh` 物件（共 18 個），OBJ 則整個模型是一個物件 `miki`：

```sh
castplane import examples/meshes/miki.glb --inline -o miki_glb.json   # 18 個物件，內嵌 data，約 0.3 秒
castplane import examples/meshes/miki.obj --inline -o miki_obj.json   # 一個物件 miki（4469 個面）
```

匯入的場景用預設的包圍盒相機與預設平行光，所以和 `miki.json` 的畫面不同；也**不等於** `miki.json`：glTF 沒有平滑群組，線稿只能用法線夾角（30°）判斷特徵邊，設計好的線與平滑曲面上的輪廓頂點因此多很多，10 個物件超過 64 個特徵輪廓頂點、發 `MESH_RAYS_CAPPED`（對匯入的檔案跑 `info` 子命令會列出；SVG 約 870 KB，`miki.json` 的是約 200 KB）。OBJ 保留了平滑群組，但整個模型是一個物件，也超過上限發一個 `MESH_RAYS_CAPPED`。要畫圖或練習請用 `miki.json`。

**重新產生。** `miki.json` 與 `meshes/miki.{obj,mtl,glb}` 全由 `tools/make_miki_model.py` 產生（確定性：連跑兩次得到逐位元組相同的檔案，在不同的 numpy / BLAS 建置上也相同；`tests/test_miki_model.py` 逐位元組比對）。**不要手改這些檔案**，改 `tools/miki_model/` 再重新產生：

```sh
python3 tools/make_miki_model.py                        # 建模、驗證，寫出 examples/miki.json 與 examples/meshes/miki.{obj,mtl,glb}（約 20 秒）
python3 tools/make_miki_model.py --check                # 另做場景檢查與渲染（警告必須為空），並印出面數預算表
python3 tools/make_miki_model.py --preview DIR          # 另寫著色的總覽圖與頭部特寫到 DIR（需要 Pillow 與 cairosvg）
python3 tools/make_miki_model.py --lines DIR            # 另渲染各視角的線稿到 DIR（--lines-views 選視角，--no-hidden 略過消隱）
```

預算是 6000 個多邊形、10000 個三角形（目前 4469 與 8154），每個物件最多 64 個特徵輪廓頂點（`MESH_MAX_RAYS`）；超過預算或有警告時產生器以結束碼 1 結束。細節見 `docs/USAGE.md` 的「`tools/make_miki_model.py`」一節。

## `reiya.json` 的用法

> **著作權聲明：** Reiya（レイヤ）及其設計屬於她的創作者。`reiya` 範例與相關檔案是依創作者的設計稿做成的畫畫參考模型，**該角色及其模型不在本專案的授權散布與傳播範圍內**（GPL-3.0 只涵蓋 castplane 軟體）。完整聲明見 [`COPYRIGHT_NOTICE.md`](../COPYRIGHT_NOTICE.md)。

**網頁。** 在 Example 選單選 `reiya`，3D 畫面與旁觀視角窗格會用各物件的 `display_color` 上色（頭髮鮭魚粉、外套與手臂鏽褐、背心裙海軍藍、上衣與襪子白、鞋子棕、釦子金，頭髮底面的襯裡是淡薰衣草）。幾個要注意的地方：

- 取消勾選 **labels** 圖層：網格的每個頂點（5530 個）都有標籤，開著會把畫面蓋滿。
- 旁觀視角窗格的「視線」勾選框（預設開啟）會畫出從眼睛到第一個物件——頭頂兩個耳朵形的髮束「tufts」（152 個頂點）——每個頂點的視線（以及它的光線），可以看出髮束在透視中的位置；取消勾選就能看到不被遮擋的整個人物。
- **form_shadow** 與 **cast_shadow** 的填色**不做消隱**（只有線會依 `hidden_lines` 切成可見與隱藏），所以背光的頭髮會透出來；cast_shadow 是每個物件各畫一個半透明的填色加輪廓，物件重疊的地方（頭、頭髮、鮑伯頭、髮束與臉上的零件；外套蓋在背心裙上；手臂與裙子）會疊得更深、也看得到內側的輪廓，練習時描外輪廓即可。cast_shadow 也不被腿與鞋子擋住。
- 要看她的側面、背面或俯仰，拖旁觀視角窗格裡的**橘色圓環**環繞（5° 吸附，按住 Alt 暫停）；「前」按鈕是沿 +y 看她的臉。焦距滑桿改視野。載入或放開滑鼠後會補上含消隱的靜止影格，拖曳時不做消隱，放開後才補上消隱後的線稿。以 `node tools/web_frame_bench.mjs <場景> 5` 在同一個環境交錯量（2026-11-01 去掉折疊薄片、調整皮膚之後，空閒的容器，四輪、每輪 `miki` 先量，取各輪中位數的中位數）：`reiya` 的靜止影格約 2.8 秒、拖曳每格約 100 ms、階段 A 約 267 ms，同一時段的 `miki` 是約 3.1 秒、71 ms、約 197 ms，所以 `reiya` 的靜止影格不比 `miki` 慢（四輪都快，中位數快 9 %），拖曳每格則比 `miki` 慢（範圍重疊），中位數在 `tools/web_frame_bench.mjs` 的 120 ms 目標內，但單輪可能碰到 108–124 ms，餘裕比之前薄。這些數字隨容器與負載而變（`miki` 在較早的環境量到約 1.4 秒），要比較請在同一環境交錯量。
- 網頁的「Download scene (current camera)」對網格場景寫出的檔案，`castplane validate` / `render` 可以直接吃（面的索引寫成整數，見合約 §5.4 實作註記），並重現網頁上同一張 SVG；`display_color` 也會寫回。

**命令列。**

```sh
castplane render examples/reiya.json -o out             # out/reiya.svg 與 out/reiya.json（約 5–7 秒；消隱開啟）
castplane render examples/reiya.json -o out --formats svg,png --layers objects,cast_shadow --dpi 150
castplane info examples/reiya.json                      # 地平線、消失點與警告表（警告為空）
```

**其他 3D 軟體與匯入。** `meshes/reiya.obj`（加 `reiya.mtl`：18 種材質，115 個零件各用其一，`display_color` 就是每個物件的主要材質色）與 `meshes/reiya.glb`（27 個節點）是同一個模型，給 Blender 等軟體用。`castplane import` 讀 GLB 時一個節點變成一個 `mesh` 物件（共 27 個），OBJ 則整個模型是一個物件 `reiya`：

```sh
castplane import examples/meshes/reiya.glb --inline -o reiya_glb.json   # 27 個物件，內嵌 data，約 0.4 秒
castplane import examples/meshes/reiya.obj --inline -o reiya_obj.json   # 一個物件 reiya（6354 個面）
```

匯入的場景用預設的包圍盒相機與預設平行光，所以和 `reiya.json` 的畫面不同；也**不等於** `reiya.json`：glTF 沒有平滑群組，線稿只能用法線夾角（30°）判斷特徵邊，設計好的線與平滑曲面上的輪廓頂點因此多很多，14 個物件超過 64 個特徵輪廓頂點、發 `MESH_RAYS_CAPPED`（對匯入的檔案跑 `info` 子命令會列出；SVG 約 1.1 MB，`reiya.json` 的是約 270 KB）。OBJ 保留了平滑群組，但整個模型是一個物件，也超過上限發一個 `MESH_RAYS_CAPPED`，另有 `MESH_WINDING_FIXED`（面的繞向被重新定向）；鮑伯頭三個殼互不共用頂點也沒有重合的面，所以 castplane 把整個檔案的頂點焊在一起後仍是封閉流形。要畫圖或練習請用 `reiya.json`。

**重新產生。** `reiya.json` 與 `meshes/reiya.{obj,mtl,glb}` 全由 `tools/make_reiya_model.py` 產生（確定性：連跑兩次得到逐位元組相同的檔案，在原生、`OPENBLAS_CORETYPE=Haswell` 與 Python 3.10 的 numpy 2.2.6 上也相同；`tests/test_reiya_model.py` 逐位元組比對）。**不要手改這些檔案**，改 `tools/reiya_model/` 再重新產生：

```sh
python3 tools/make_reiya_model.py                       # 建模、驗證，寫出 examples/reiya.json 與 examples/meshes/reiya.{obj,mtl,glb}（約 15 秒）
python3 tools/make_reiya_model.py --check               # 另做場景檢查與渲染（警告必須為空），並印出面數預算表（約 23 秒）
python3 tools/make_reiya_model.py --preview DIR         # 另寫著色的總覽圖與頭部特寫到 DIR（需要 Pillow 與 cairosvg）
python3 tools/make_reiya_model.py --lines DIR           # 另渲染各視角的線稿到 DIR（--lines-views 選視角，--no-hidden 略過消隱）
python3 tools/make_reiya_model.py --out-dir OUT --overlay SHEET.png DIR   # 疊圖檢查：把模型疊在設計稿上量差異與平滑度（約 45 秒；設計稿與 DIR 都在儲存庫之外）
```

預算是 6500 個多邊形、10600 個三角形（目前 6354 與 10576，還剩 146 個多邊形與 24 個三角形；修整前是 6000 與 10000，模型超出後先放寬為 6500 與 10500，使用者在 2026-11-01 決定保留放寬，加上葉形髮尾後三角形的上限取到 10600，依據是修整完成時網頁靜止影格不比 `miki` 慢；之後去掉折疊薄片讓鮑伯頭少了 16 個三角形），每個物件最多 64 個特徵輪廓頂點（`MESH_MAX_RAYS`，目前最多的 `top` 有 51 個）；超過預算或有警告時產生器以結束碼 1 結束。模型以設計稿的比例建好，再整體縮放到 1.52 m 的身高（`rig.figure_scale`，腳底仍在 z = 0）。細節見 `docs/USAGE.md` 的「`tools/make_reiya_model.py`」一節、維護指南 [`tools/reiya_model/README.md`](../tools/reiya_model/README.md)（物件與材質、身高縮放、零件規則、檢查與已知限制）與角色規格 [`tools/reiya_model/SPEC.md`](../tools/reiya_model/SPEC.md)。

**修整（2026-10-31）與疊圖檢查。** 使用者檢閱後，模型做了一輪修整：暖色皮膚、平滑的鮑伯頭（每側 13 條鐘形欄、依設計稿分層的髮絡與縫隙）、更圓鼓的燈籠袖與收攏的袖口、放鬆的手與手臂。完成度用數字檢查：`--overlay` 以正交投影（長焦鏡頭的極限）把她的正面、側面與背面畫進設計稿的像素格，各以 50 % 的透明度疊在設計稿上，報告每個地標差幾 mm、各色塊的 IoU，以及鮑伯頭、袖子與頭頂的平滑度（同一平滑群組內相鄰面的最大夾角、輪廓的最大轉角）。41 條通過條件是資料（`tools/reiya_model/overlay.py` 的 `CRITERIA`，P1 必須通過、P2 應該通過），報告 `report.md` 的第一張表列出每一條的數值、上限與通過與否。修整完成時 35 條通過、1 條（M5）沒有東西可量、5 條未通過（P1 一條：鮑伯頭輪廓的轉角，P2 四條）；使用者決定把鮑伯頭的髮絡末端做成葉形（2026-11-01）之後，鮑伯頭輪廓的轉角通過了（第 95 百分位 13.75°，上限 15°），再去掉背後縫隙的折返薄片之後降到 11.83°（餘裕約 3.2°）；目前 36 條通過、1 條（M5）沒有東西可量、4 條未通過，都是 P2（正面的髮型 IoU 0.7961 對 0.80、袖子內緣、頭頂的刻面兩條），清單與原因在 [`tools/reiya_model/README.md`](../tools/reiya_model/README.md) 的「Open after the finishing pass」。皮膚在 2026-11-01 又調成帶玫瑰色的 `#fad8cd`（`tools/reiya_model/SPEC.md` 的 Decision 33）。設計稿不在儲存庫裡。
