# 範例場景

每個檔案都是 spec §4 格式的場景 JSON，可直接 `castplane render examples/<名稱>.json -o out`。除了 `miki.json`（直式，見表末那一列）以外，全部使用 36×24 mm 片幅、273×182 mm 畫布（3:2，見 docs/DECISIONS.md 關於 257×182 的說明）。

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
| `miki.json` | 花菱美希（《ハヤテのごとく!》）的角色參考模型，給畫畫練習用：1.51 m 的動漫女學生（5.9 頭身），放鬆的 A 字站姿，站在原點的地面上、面向 −Y。**這是唯一的直式範例**：片幅 24×36 mm、畫布 182×273 mm（2:3），是本檔開頭那句話的例外；相機在 (1.7, −3.4, 1.25)、焦距 65 mm，場景給的是一盞太陽（平行光，方向 (−0.335, −0.409, 0.849)）。共 18 個 `mesh` 物件，每個都是內嵌 `data` 的一組空間上緊湊的封閉殼（共 58 個零件殼）：`headband`、`hair`、`head`、`eyes`、`scarf`、`sidelocks`、`blouse`、`collar`、`back_hair`、`arm_l`、`face_marks`、`arm_r`、`legs`、`socks`、`skirt`、`shoes`、`ring`、`neck`（分成 18 個是為了讓消隱快；4181 個頂點、4469 個多邊形、8154 個三角形）。預設圖層是 `objects` 與 `cast_shadow`，`output.hidden_lines` 開啟且 `hidden_style` 為 `omit`，所以被擋住的線不畫（線稿而不是虛線的透視圖）。無警告（`warnings` 為空）。每個物件另有選用的 `display_color`（`"#rrggbb"`，取該物件的主要材質色，如頭髮 `#b9c3e6`、上衣 `#e8667a`），只給網頁的 3D 畫面上色，核心與 SVG / JSON 完全忽略它（D81）。 |

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
