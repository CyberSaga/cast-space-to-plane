# 一致性測試集（spec §7.5）

一致性測試集是 castplane 的**輸出合約**：固定一組場景輸入與對應的幾何輸出，任何實作（Python 參考實作、未來的 TypeScript 移植）都必須在規定的容差內重現這些輸出。擴充功能時先改測試集、再改實作；測試集的每一次變更都要記錄版本與原因。

## 位置

| 路徑 | 內容 |
| --- | --- |
| `cases/<案例>.json` | 輸入：一個 spec §4 格式的場景檔，外加一個說明用的 `description` 欄位（驗證時會被忽略，contract §2.0「未知鍵忽略」） |
| `expected/<案例>.json` | 輸出：`castplane.render(scene)["geometry"]` 經 `castplane.output.geometry_json.dumps` 寫出的 spec §6.2 幾何文件（contract §3.1 鍵、排序鍵、最短往返浮點數、結尾換行） |
| `CHANGELOG.md` | 版本紀錄：每次重新產生 expected 的日期、版本號、案例清單與原因 |
| `rules.json` | 比對規則常數的單一來源（v3 起，合約 §5.4.8 / §5.0.8）：`image_tol_mm`、`rel_tol`、`mm_keys`、`drawable_containers`、`arc_non_mm`、`mm_key_paths`、`int_keys`、`max_reported` 與逐案例的 `case_overrides`（M4 加 `runs_rule`）；Python 執行器保留自己的常數並以測試斷言兩者相等，TypeScript 執行器直接讀這個檔 |
| `../test_conformance.py` | 比對程式（pytest） |
| `../../tools/regen_conformance.py` | 重新產生 expected 檔的工具 |

案例 id 就是檔名主幹；`cases/` 與 `expected/` 必須一一對應（測試會檢查）。

## 比對規則

`tests/test_conformance.py` 把每個案例重新渲染，與 expected 檔逐一路徑比對：

| 項目 | 規則 |
| --- | --- |
| 畫面座標（canvas mm） | 絕對容差 **1e-6 mm**。包含 `points[].image`、所有可畫圖形：`edges[].segment`、`shadows[].polygons`、`form_shadow[].polygons`、`outlines[].generators[].segment`、圓錐曲線項目的 `polylines` / `arcs` / `ellipses`（其中 `rotation_deg`、`theta`、`large_arc`、`sweep` 除外）、`construction.segments[].points`、`construction.light_point` / `shadow_vp`、`construction.checks[].max_error_mm`、`horizon.v_mm` / `segment` / `vanishing_points`、`camera.principal_point`、`canvas_mm` |
| 其他數值（世界座標、深度、方向、圓錐曲線矩陣、相機矩陣、角度） | 相對容差 **1e-9**，下限 1e-9：`|a − b| ≤ 1e-9 · max(1, |a|, |b|)` |
| 非數值（字串、布林、null、串列長度、物件鍵） | 完全相等。整數與浮點數都視為數值（移植版可把 `1.0` 寫成 `1`），布林不是數值 |
| `warnings` | **代碼集合**必須相同（spec §7.5）；`(code, ids)` 的集合也必須相同（contract §2.9 規定 ids）；`message` 不比對 |
| `runs` 項目內的數值（M4，`rules.json` 的 `runs_rule`，合約 §5.0.8 / §5.1.11） | 任何 `runs` 串列項目（邊、母線、明暗交界線段、圓錐曲線項目、`polygon_edges`）內：`mm` 絕對容差 **0.05 mm**，`s` / `t` / `theta` 絕對 **1e-3**（`theta` 在 runs 內不套 `arc_non_mm`），`visible`、`interval` 與段數完全相等。取樣式消隱的邊界本身只準到 `HLR_TOL_MM`，不能用 1e-6 mm 比對 |
| M4 其他新鍵 | `hidden_polylines` 是畫面座標（1e-6 mm）；`construction.per_receiver.*.segments.*.points` 也是（`mm_key_paths`）；`interval` 是整數鍵（`int_keys`）；`receivers[].plane` / `bounds` 等其餘新數值照上面的 1e-9 相對容差 |
| M6 多光源鍵（**只出現在多光源文件**，`len(lights) ≥ 2`，合約 §5.3.5） | `umbra[].polygons` 是畫面座標（`polygons` 本來就是 mm 鍵，1e-6 mm，逐片、逐頂點依索引比對）；`constructions.*.segments[].points` 與 `constructions.*.per_receiver.*.segments[].points` 是畫面座標（`rules.json` 的 `mm_key_paths`，v6），`constructions.*.light_point` / `shadow_vp` / `checks[].max_error_mm` 走既有的 mm 鍵；`umbra[].lights`、`edges[].silhouette_lights`、`form_shadow[].light` 完全相等；`constructions` 每個光源一個 M4 作圖區塊，`construction` 是第一個光源那一塊的別名。單光源文件沒有這些鍵（缺鍵或多鍵都是鍵集合不符） |

失敗訊息會列出案例名稱與不符的路徑（例如 `points.crate.v0.image[0]: expected …, got …`），最多列 25 條。

**逐案例放寬（`rules.json` 的 `case_overrides`，v3）。** 一筆放寬只對一個案例、只對路徑符合其 `paths`（`*` 代表任一個串列索引或鍵，比對路徑前綴）之下的**數值**改用絕對容差 `abs_tol`；非數值、串列長度、鍵集合與警告一律不放寬。目前只有一筆：`degenerate_cylinder_cap_at_light_height` 的 `shadows[*].loops[*][*].direction` 與 `shadows[*].outline[*].direction`（四個葉節點）以 1e-6 絕對容差比對——頂蓋恰在光源高度，`w_S = 0` 的交點是重根，方向頂點對 `M`、`L` 一個 ulp 的擾動以平方根放大（實測每 ulp 1.5e-9），這是案例的目的而非實作錯誤（合約 §5.4.4 (1)、D60）。`compare_documents(expected, actual, case_name)` 依案例名稱套用。

## 來源（目前版本 v8，見 `CHANGELOG.md`；共 63 個案例：34 個 v2 案例，M4 的 9 個見下方 `### M4 受影面與隱藏線`，M5 的 3 個見 `### M5 網格`，M6 的 4 個見 `### M6 多光源`，最終審查修正的 10 個見 `### v7 最終審查修正`，M10 的 3 個見 `### M10 投影平面`）

| 類別 | 案例 | 依據 |
| --- | --- | --- |
| 解析案例 | `analytic_unit_box_point_light_overhead`、`analytic_sun_45deg_box`、`analytic_sun_30deg_box`、`analytic_sphere_oblique_directional`、`analytic_camera_level`、`analytic_camera_pitched` | spec §7.2 四條 |
| 退化情況 | `degenerate_light_behind_viewer`（列 1）、`degenerate_light_parallel_to_picture_plane`（列 2）、`degenerate_directional_horizontal`（列 3）、`degenerate_vertex_above_point_light`（列 4）、`degenerate_point_behind_camera`（列 5）、`degenerate_face_parallel_to_light_point` / `_directional`（列 6）；另有 contract §2.3 / §2.6 / §2.7 的 `degenerate_light_below_receiver`、`degenerate_vertical_directional_light`（F 未定義）、`degenerate_light_at_camera_centre`（L′ 未定義）、`degenerate_light_inside_sphere`、`degenerate_cylinder_cap_at_light_height` | spec §5.7 每列至少一例 |
| 範例場景 | `example_basic`（spec §4 範例）、`example_construction_demo`、`example_curved_demo`、`example_three_point`、`example_directional` | `examples/*.json` |
| 凹多邊形 | `concave_prism_light_foot_in_notch`（光源垂足在 U 形稜柱的凹口內，由 `tests.reference.random_scenes.make_concavity_scene(1)` 凍結） | spec §7.3 |
| 部分埋入地面 | `buried_box_tilted`、`buried_cylinder_tilted`（曲面物件的地面截面鏈） | contract §2.3 / §2.6 |
| 相機 | `camera_roll_and_shift`、`camera_yaw_pitch_form`；第三種相機形式 `picture_plane` 的 3 個案例見 `### M10 投影平面` | contract §2.1 / §2.2、§5.7 |
| 亂數場景 | `random_seed{0,3,9,14,23,38}_*objects`：`tests.reference.random_scenes.make_scene(seed, n_objects)` 產生、通過 §7.3 光線投射對照（IoU ≥ 0.99，含逐物件比對）後凍結；五種基元與兩種光源都有涵蓋 | spec §7.3 |

### M4 受影面與隱藏線

合約 §5.1.11 的 9 個案例，在 M4 工作樹中以 `regen_conformance.py --case` 加入（場景取自 `tests/test_receivers.py` / `tests/test_hidden.py` 的場景產生函式）。34 個既有案例的 expected 檔在工作樹中**不動**：M4 給每份文件加上無條件的新鍵（`hidden_lines`、`receivers`、`construction.per_receiver`、`runs`、`visibility`、`hidden_polylines`、`polygon_edges`），整組的鍵新增重產（v4）在合併後的主分支上只做一次（合約 §5.0.8 第 2 條）；在那之前，`test_render_matches_expected` 對沒有 `hidden_lines` 鍵的 expected 先以 `strip_new_keys` 刪掉這些鍵（並檢查它們都是關閉時的值）再比對。`python3 tools/regen_conformance.py --strip-new-keys --reason "…"` 是同一個檢查的命令列版本（不寫檔；已帶 M4 鍵的 expected 直接比對），v4 那一筆 CHANGELOG 要記錄它零不符。

| 案例 | 內容 | 依據 |
| --- | --- | --- |
| `wall_and_ground` | 手算驗收案例：無界地面 + 有界牆面 y = 6（法線 −y）、點光源下的木箱；影子從地面折到牆上，轉折點 (±3/4, 6, 0)；消隱關閉、無警告 | 合約 §5.1.11、spec §10 M4 |
| `wall_and_ground_hidden` | 同上、`hidden_lines` 開啟：牆底邊 `partial`（s = 23/60、37/60）、地面影子邊在 y = 6 之後被牆遮住（s = 0.713073）、木箱 5 條隱藏邊 / 7 條可見邊 | 合約 §5.1.11 |
| `receiver_unlit_wall` | 光源在牆後（0, 8, 3）：`RECEIVER_UNLIT [lamp, wall]`，牆收不到影子（紀錄為空）但仍對地面投影；牆頂的地面影子落到相機後方，`POINT_BEHIND_CAMERA` 的 ids 是受影面 id `wall` | 合約 §5.1.2 / §5.1.9 |
| `receiver_directional_wall` | 平行光、水平視線：`F.sun.wall` 是方向點且其影像在無窮遠，`SHADOW_VP_AT_INFINITY [sun, wall]`，`construction.per_receiver.wall.shadow_vp_at_infinity` | 合約 §5.1.5 |
| `fold_curved_cylinder` | 圓柱影子從地面折到牆上：圓錐曲線影子在有界受影面上的閉式 bounds 裁切 | 合約 §5.1.4 |
| `bounded_default_receiver` | 沒有地面，`receivers[0]` 是有界地板：它擁有短點名與平的 `construction` 鍵；木箱影子在 y = 5.5 被 bounds 截斷 | 合約 §5.1.2 |
| `hidden_lines_curved_unbounded` | 比光源高的球與圓柱（無界地面影子：雙曲線分支、開口的圓柱影子），消隱開啟：圓錐曲線 runs、`hidden_polylines`、母線 runs | 合約 §5.1.6 / §5.1.11 |
| `hidden_lines_vp_in_canvas` | `degenerate_vertex_above_point_light` 開啟消隱：影子多邊形有一個頂點在擴大畫布內的地平線上，畫出的邊有 `w = 0` 端點 | 合約 §5.1.6.4 / §5.1.11 |
| `concave_prism_on_plate` | U 形稜柱、光源在凹口內且低於臂頂、地板 [−3, 3] × [−4.5, −2] 在封閉臂之後：未裁切影子的無窮遠弧超過 180°，錨點規則讓結果是整塊板（面積 15） | 合約 §5.1.3.3（錨點規則） |

### M5 網格

| 類別 | 案例 | 依據 |
| --- | --- | --- |
| 焊接＋三角化的方塊 | `mesh_box_welded_triangulated`：`analytic_unit_box_point_light_overhead` 的方塊換成 24 個分裂頂點、12 個三角形的內嵌網格；焊接與共面合併後與參數化方塊完全相同，expected 檔除了 12 條邊上的 `smooth` / `camera_silhouette` 兩個網格專用鍵以外與 `analytic_unit_box_point_light_overhead` **逐字相同**（測試會檢查） | 合約 §5.2.12 驗收 1 |
| 非流形退路 | `mesh_open_bottom_box_fallback`：沒有底面的方塊（頂面＋四個側面）→ `MESH_NON_MANIFOLD`、逐面影子 5 個迴圈、聯集為 ±0.75 的正方形、沒有作圖線與 checks | 合約 §5.2.5、§5.2.12 驗收 2 |
| 平滑邊 | `mesh_smooth_prism16`：16 邊形稜柱；16 條側邊是平滑邊（二面角 22.5° < 30°），只有成為相機輪廓的 2 條會畫出（其餘 `segment: null`），頂底面的邊全是特徵邊 | 合約 §5.2.4 |

**案例是展開後的場景，網格案例一律內嵌 `data`**（合約 §5.0.2、§5.2.9）：`cases/` 裡的 `mesh` 物件只有 `data`、沒有 `path` / `node`，也不會出現只在載入器層存在的 `step` 型別；TypeScript 移植因此不需要任何載入器（`test_cases_are_post_expansion_scenes_with_inline_mesh_data` 檢查）。M5 只用 `--case` 新增這三個案例，既有的 expected 檔一個都沒變。

### M6 多光源

合約 §5.3.10 的 4 個案例，在 M6 工作樹中（已合併 v5）以 `regen_conformance.py --case` 加入（合併時與 `--rules-only` 條目收成一筆 v6 條目），既有的 expected 檔一個都沒變（加入前 `--dry-run`：46 個 v5 案例 0 個會變）。多光源的鍵是**有條件的**：只有 `len(lights) ≥ 2` 的文件才有 `constructions`、`umbra`、`form_shadow_core`、`form_shadow[].light`、`edges[].silhouette_lights`，所以單光源案例不受影響（`test_m6_cases_are_multi_light_documents` 檢查）。`rules.json` 加了 `constructions` 的兩條 mm 路徑（`--rules-only`）。

| 案例 | 內容 | 依據 |
| --- | --- | --- |
| `multilight_two_point_symmetric_box` | 手算驗收案例：單位立方體、兩盞對 x 鏡射的點光源 `west` (−2, 0, 2) / `east` (2, 0, 2)；每盞光的影子紀錄與它單光源文件位元相同；本影 3 片（三角形、四邊形、三角形，影像面積 `132.85761502560047`、`1315.4880281807557`、`90.38709809014404` mm²，反投影回地面面積 7/6）；`form_shadow_core` = ±y 面與底面；`silhouette_lights` 逐邊；無警告（`test_acceptance_expected_file_holds_the_hand_values` 檢查手算值） | 合約 §5.3.10、spec §10 M6 |
| `multilight_point_and_directional_curved` | 球 `ball`、圓柱 `pillar`、稜柱 `wedge`，點光源 `lamp` + 平行光 `sun`：曲面物件依光源命名的基點（`ball.sil.0.lamp`、`pillar.g0.base.sun` …，影子點 `ball.sil.0.sun.shadow.sun`）、每個 (光源, 曲面物件) 一筆明暗交界線 `form_shadow`、取樣曲面影子多邊形的本影、`wedge` 的 core 面 | 合約 §5.3.2、§5.3.10 |
| `multilight_three_lights_concave_prism` | `N = 3`：`make_concavity_scene(1)` 的 U 形稜柱與方塊再加兩盞點光源；`light_b`、`light_c` 的影子迴圈自交，三盞光的區域重疊，本影 = 三個 nonzero 區域的交集（每盞光一個計數器）。兩個投影物**離地 0.2 m**：站在地上的物件在各光源的迴圈共用接地頂點與接地邊，會讓本影的**分片**（不是區域）隨建置的捨入而變（合約 §5.3 實作筆記），離地後每個判定都離門檻夠遠，可以逐片比對（`test_three_light_case_pieces_are_stable_under_rigid_motions` 檢查） | 合約 §5.3.4、§5.3.7、§5.3.10 |
| `multilight_second_light_inactive` | 驗收立方體、`west` 有效、第二盞點光源 `under` 在地面以下：`LIGHT_BELOW_RECEIVER [under]`、它的紀錄為空、`receivers[0].lit = {west: true, under: false}`、`umbra[0].lights = [west]`、`polygons = []`（有效光源少於兩盞）；SVG 中唯一有效的光源群組 `fill-opacity="0.3"`，本影群組為空 | 合約 §5.3.8、§5.3.10 |

### v7 最終審查修正

M4–M8 合併後的最終審查修正（分支 `wt/fix-arc`、`wt/fix-loaders`、`wt/fix-misc`）留下的 10 個場景，各組先放在 `tests/fixtures/v7_candidates/`（不執行工具），合併時以 `regen_conformance.py --case` 一次加入，收成一筆 v7 條目；既有的 expected 檔一個都沒變（加入前 `--dry-run`：50 個 v6 案例 0 個會變）。

| 案例 | 內容 | 依據 |
| --- | --- | --- |
| `arc_pairing_arch_ground` | 拱形稜柱立在地上、燈在橫梁下：一條輪廓迴圈穿過光平面 4 次，弧依角度括號配對，得到兩個無界地面迴圈（光線投射一致）；v1 依迴圈順序配對會塗黑整個地面 | 審查 m4-geometry#0、合約 §5.1 實作筆記「Arc pairing」、D70 |
| `arc_pairing_u_wall` | 轉 25° 的 U 形稜柱跨過「過燈且平行於牆」的平面：牆上影子為**空**（修正前整塊 15 m² 牆板） | 同上 |
| `arc_pairing_u_notch_wall` | U 形稜柱、燈在凹口內、牆在**開口**後方：牆上兩個迴圈（兩臂的影子），IoU ≥ 0.99 | 同上 |
| `arc_pairing_u_on_side` | 同一個 U 側躺在離地 2 m 處、燈在凹口內：地面路徑有兩段延伸到無窮遠，兩個地面迴圈 | 同上 |
| `arc_pairing_u_closed_arm_wall` | 牆在**封閉**臂後方：`p = 2` 的牆上迴圈，角度配對與迴圈順序一致，與 v1 的掃角位元相同 | 審查 m4-geometry#0 第二輪 |
| `arc_base_level_spiral_upright` | 1.3 圈的螺旋稜柱、燈在內部半高：光平面的每個方向都打到物體，`p = 1` 迴圈的弧在基準層修正後掃過一整圈以上（地面 IoU 1.00，修正前 0.26） | 合約 §5.1 實作筆記「Base level of the arcs at infinity」 |
| `arc_base_level_spiral_tilted` | 同一螺旋先轉 30° 再繞 x 傾斜 15°：`p = 2`，第一段弧多加一圈 | 同上 |
| `arc_base_level_spiral_floor` | 直立螺旋加 `z = 0.25` 的有界水平板：受影面座標框上的基準層修正，加上超過 2π 的弧經邊界裁切 | 同上 |
| `mesh_noisy_l_ground_contact` | 凹 L 形網格（內嵌 `data`），底面頂點 v3、v5 在地面下 1e-7 m（在 1e-6 的焊接容差內）：網格的受影面接觸容差 `max(tol, weld_tolerance)` 保持乾淨的 L 形輪廓，沒有 `OBJECT_BELOW_RECEIVER` | 審查 m5-mesh#0、合約 §5.2 實作筆記 |
| `multilight_mesh_fallback_shared_edges` | 開口的 UV 球殼（144 面，走 M5 逐面備援）在兩盞點光源下：本影核心第 5 步橋接零寬區間，共用邊不再切開分割，本影 14 片（修正前 514 片） | 審查 m6-umbra#0、合約 §5.3.4 |

### M10 投影平面

合約 §5.7.14 的 3 個案例：相機以第三種形式 `position` + `picture_plane {normal, offset, up?}` 給出（spec-v0.2 §4.1），在 B 段之前換算成 target 形式；只有這種文件帶 `camera.picture_plane {normal, offset, up, distance, foot, frame_m, equation}`。場景先由 Python 核心放在 `tests/fixtures/v8_candidates/`，TypeScript 移植合併後以 `regen_conformance.py --case`（三個案例一次）加入，收成一筆 v8 條目；既有的 expected 檔一個都沒變（加入前 `--dry-run`：60 個 v7 案例 0 個會變），`rules.json` 不變（`equation` 字串完全比對，其餘數值走 1e-9 相對容差）。每個案例的影像座標都等於手寫的等價 target 相機（`tests/test_picture_plane.py`、`ts/test/picture_plane.test.ts` 檢查），方程式字串的每個數字離捨入邊界都超過 1e-6。

| 案例 | 內容 | 依據 |
| --- | --- | --- |
| `camera_picture_plane_vertical` | spec-v0.2 §4.1 的板子：平面 `y = 2`（法線 (0, 1, 0)、offset −2）、眼睛在 y = −2，`D = 4`、`frame_m = [7.2, 4.8]`、方程式 `"y = 2.00"`；方塊與圓柱、點光源 | 合約 §5.7.2、§5.7.4、§5.7.14 |
| `camera_picture_plane_tilted` | 斜板：未正規化、法線指回眼睛的平面 −0.35x − y + 0.25z + 1.4 = 0（f = −n̂），給定 `up = (0.15, 0, 1)` 使畫框滾轉（ρ ≠ 0）；方程式 `"0.322x + 0.919y - 0.230z = 1.286"`；方塊與圓錐 | 合約 §5.7.3、§5.7.5 |
| `camera_picture_plane_horizontal` | 水平板 `z = 3` 由正上方往下看：`f = (0, 0, −1)`、畫框 up 取 +y 退路，**不發** `CAMERA_LOOKING_ALONG_UP`，地平線 `null`；只用多面體（正上方看到的水平圓會成為正圓，其 `rotation_deg` 落在 ulp 放大邊界），光源離相機軸夠遠 | 合約 §5.7.3、§5.7.14 |

**M8（STEP 匯入）不新增、不改動任何案例或 expected 檔**（合約 §5.0.8、§5.5.10）：案例永遠不含只存在於載入器層的物件（`type: "step"`、帶 `path` 的 `mesh`），它們都是展開後的場景；STEP 的驗收（`cylinder.step` 展開後渲染與 `expected/example_basic.json` 逐位元相同、`cylinder_tilted.step` 通過 `expected/buried_cylinder_tilted.json` 的比對）在 `tests/test_step.py` 裡以既有的 expected 檔做。

每個案例刻意只放少量物件，讓 expected 檔可以人工審閱；整組 expected 的大小必須 < 3 MB（測試會檢查）。

## 規則

1. **先加案例、再改實作。** 新功能或行為變更先寫進 `cases/`，用工具產生 expected，確認差異合理後才改程式。
2. **版本化。** expected 檔只能由 `tools/regen_conformance.py` 產生，不得手改（測試檢查檔案為 `geometry_json.dumps` 的標準形式）。工具強制要求 `--reason`，並在 `CHANGELOG.md` 追加一筆 `## v<N> — <日期>`：版本號、重新產生的案例清單、未變更的案例與原因。`v<N>` 就是測試集版本；每筆也記錄產生檔案的 Python / NumPy 版本。expected 檔只在該版本的直譯器／NumPy 上**位元相同**（別的 libm 會在少數葉節點的最後幾位有 ≈ 1e-12 的差異，容差比對仍全數通過）；`test_regen_tool_exit_codes_match_its_docstring` 只在「同一建置」時要求 `--dry-run` 零差異，否則只要求每個有差異的案例仍通過上表的容差。「同一建置」由 `tests/build_identity.py` 的 `exact_build()` 判定：NumPy 版本與紀錄相同，**且** 建置指紋（一組 ufunc 與線性代數結果的雜湊，記在 `tests/golden/build_fingerprint.json`）相同——同一個 NumPy wheel 會依 CPU 選用不同的 OpenBLAS 核心與 SIMD 迴圈（例如 GitHub 託管 runner 的 Haswell/Zen 核心與記錄機器的 SkylakeX 核心），只比版本號不足以保證位元相同。重新產生測試集的機器須同時執行 `python -m tests.build_identity --write` 更新指紋。
   **比對規則也版本化（v3 起）。** `rules.json` 的任何修改都是一致性合約的修改：改完檔案後執行 `python3 tools/regen_conformance.py --rules-only --reason "…"`，工具不渲染、不碰 `expected/`，在 `CHANGELOG.md` 追加一筆 `## v<N>`（「comparator amendment, no expected file changed」），列出與上一筆紀錄的規則差異並完整記下新規則；`rules.json` 未變時拒絕記錄（結束碼 1），`--rules-only` 不能與 `--case` 併用（結束碼 2）。測試檢查最後一筆紀錄的規則等於 `rules.json`，所以比對器不能被悄悄放寬。這種條目不記錄建置版本（沒有渲染任何檔案），位元相同的判定沿用前一筆有 `build` 的條目。
3. **TypeScript 移植必須全數通過**（spec §9、§10 M7）：移植版讀取 `cases/*.json`，產生同格式文件，依上表規則與 `expected/*.json` 比對。Python 為參考實作；兩邊不一致時先判定哪邊違反 spec / contract，再改測試集。
   TypeScript 執行器是 `ts/test/conformance.test.ts`（合約 §5.4.8）：直接讀取倉庫中的 `cases/`、`expected/` 與 `rules.json`（不複製、不產生 expected），比對器是 `tests/test_conformance.py` 的逐字移植，同樣套用 `case_overrides`。兩個執行器必須在同一個 commit 上都通過。TS 失敗先當成 TS 的錯；若審查發現是 Python 輸出違反 spec / contract，修 Python 並以 `--reason` 重新產生（CHANGELOG 註明 TS 的發現）；若不一致來自案例刻意坐落的 ulp 放大邊界，則經 `--rules-only` 加一筆 `case_overrides`，並在 `reason` 寫下實測的敏感度。兩條路都是有版本的 CHANGELOG 條目，沒有任何東西可以悄悄改。
   M7 第二階段（合約 §5.4.0）的驗收：兩個執行器在 v6 的 50 個案例上都通過，記錄在 `CHANGELOG.md` v6 條目的「both runners green on v6」一行；TypeScript 執行器每個案例一個測試，沒有 todo 清單，CI 的 `ts` job 另外單獨執行它，有失敗、略過或 todo 的案例就讓 job 失敗。
   **已知的跨實作邊界（M7 第二輪審查，合約 §5.4 implementation notes）。** 移植版的建構射線遠端點（`construction.segments[].points`）只在 `|S' − Q'|` 不小於 `1e-3 · |L' − Q'|` 時保證落在影像容差內（頂點離受影面僅數微米時 `covering_segments` 病態，實測兩實作差到 4e-5 mm）；正圓影像橢圓的 `rotation_deg`（如球心在相機軸上）、兩個等高標籤點的物件 id 位置、點光源距相機中心 ~1e-7 m 內的 `light_point`、以及光源幾乎落在圓盤平面上的影子圓錐曲線也都坐落在 ulp 放大邊界上。新案例不得放在這些邊界上；修正規則是待維護者決定的版本化變更。
4. **退化情況以警告代碼為準。** 退化案例的重點是 `warnings` 代碼集合與輸出仍然完整有限，不是特定數值。

## 新增案例

```sh
# 1. 寫場景檔（spec §4 格式 + description），檔名即案例 id
$EDITOR tests/conformance/cases/my_case.json
# 2. 產生 expected（必須給原因），CHANGELOG.md 會自動追加一筆
python3 tools/regen_conformance.py --case my_case --reason "add my_case: <為什麼需要它>"
# 3. 檢查
python3 -m pytest tests/test_conformance.py -q
```

`--dry-run` 只報告哪些 expected 會改變、不寫檔；不加 `--case` 則重新產生全部案例（行為變更時用，並在 reason 說明變更內容）。
