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

失敗訊息會列出案例名稱與不符的路徑（例如 `points.crate.v0.image[0]: expected …, got …`），最多列 25 條。

**逐案例放寬（`rules.json` 的 `case_overrides`，v3）。** 一筆放寬只對一個案例、只對路徑符合其 `paths`（`*` 代表任一個串列索引或鍵，比對路徑前綴）之下的**數值**改用絕對容差 `abs_tol`；非數值、串列長度、鍵集合與警告一律不放寬。目前只有一筆：`degenerate_cylinder_cap_at_light_height` 的 `shadows[*].loops[*][*].direction` 與 `shadows[*].outline[*].direction`（四個葉節點）以 1e-6 絕對容差比對——頂蓋恰在光源高度，`w_S = 0` 的交點是重根，方向頂點對 `M`、`L` 一個 ulp 的擾動以平方根放大（實測每 ulp 1.5e-9），這是案例的目的而非實作錯誤（合約 §5.4.4 (1)、D60）。`compare_documents(expected, actual, case_name)` 依案例名稱套用。

## 來源（目前版本 v5，見 `CHANGELOG.md`；共 34 個 v2 案例，M4 的 9 個見下方 `### M4 受影面與隱藏線`，M5 的 3 個見 `### M5 網格`）

| 類別 | 案例 | 依據 |
| --- | --- | --- |
| 解析案例 | `analytic_unit_box_point_light_overhead`、`analytic_sun_45deg_box`、`analytic_sun_30deg_box`、`analytic_sphere_oblique_directional`、`analytic_camera_level`、`analytic_camera_pitched` | spec §7.2 四條 |
| 退化情況 | `degenerate_light_behind_viewer`（列 1）、`degenerate_light_parallel_to_picture_plane`（列 2）、`degenerate_directional_horizontal`（列 3）、`degenerate_vertex_above_point_light`（列 4）、`degenerate_point_behind_camera`（列 5）、`degenerate_face_parallel_to_light_point` / `_directional`（列 6）；另有 contract §2.3 / §2.6 / §2.7 的 `degenerate_light_below_receiver`、`degenerate_vertical_directional_light`（F 未定義）、`degenerate_light_at_camera_centre`（L′ 未定義）、`degenerate_light_inside_sphere`、`degenerate_cylinder_cap_at_light_height` | spec §5.7 每列至少一例 |
| 範例場景 | `example_basic`（spec §4 範例）、`example_construction_demo`、`example_curved_demo`、`example_three_point`、`example_directional` | `examples/*.json` |
| 凹多邊形 | `concave_prism_light_foot_in_notch`（光源垂足在 U 形稜柱的凹口內，由 `tests.reference.random_scenes.make_concavity_scene(1)` 凍結） | spec §7.3 |
| 部分埋入地面 | `buried_box_tilted`、`buried_cylinder_tilted`（曲面物件的地面截面鏈） | contract §2.3 / §2.6 |
| 相機 | `camera_roll_and_shift`、`camera_yaw_pitch_form` | contract §2.1 / §2.2 |
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

每個案例刻意只放少量物件，讓 expected 檔可以人工審閱；整組 expected 的大小必須 < 3 MB（測試會檢查）。

## 規則

1. **先加案例、再改實作。** 新功能或行為變更先寫進 `cases/`，用工具產生 expected，確認差異合理後才改程式。
2. **版本化。** expected 檔只能由 `tools/regen_conformance.py` 產生，不得手改（測試檢查檔案為 `geometry_json.dumps` 的標準形式）。工具強制要求 `--reason`，並在 `CHANGELOG.md` 追加一筆 `## v<N> — <日期>`：版本號、重新產生的案例清單、未變更的案例與原因。`v<N>` 就是測試集版本；每筆也記錄產生檔案的 Python / NumPy 版本。expected 檔只在該版本的直譯器／NumPy 上**位元相同**（別的 libm 會在少數葉節點的最後幾位有 ≈ 1e-12 的差異，容差比對仍全數通過）；`test_regen_tool_exit_codes_match_its_docstring` 只在 NumPy 版本與紀錄相同時要求 `--dry-run` 零差異，否則只要求每個有差異的案例仍通過上表的容差。
   **比對規則也版本化（v3 起）。** `rules.json` 的任何修改都是一致性合約的修改：改完檔案後執行 `python3 tools/regen_conformance.py --rules-only --reason "…"`，工具不渲染、不碰 `expected/`，在 `CHANGELOG.md` 追加一筆 `## v<N>`（「comparator amendment, no expected file changed」），列出與上一筆紀錄的規則差異並完整記下新規則；`rules.json` 未變時拒絕記錄（結束碼 1），`--rules-only` 不能與 `--case` 併用（結束碼 2）。測試檢查最後一筆紀錄的規則等於 `rules.json`，所以比對器不能被悄悄放寬。這種條目不記錄建置版本（沒有渲染任何檔案），位元相同的判定沿用前一筆有 `build` 的條目。
3. **TypeScript 移植必須全數通過**（spec §9、§10 M7）：移植版讀取 `cases/*.json`，產生同格式文件，依上表規則與 `expected/*.json` 比對。Python 為參考實作；兩邊不一致時先判定哪邊違反 spec / contract，再改測試集。
   TypeScript 執行器是 `ts/test/conformance.test.ts`（合約 §5.4.8）：直接讀取倉庫中的 `cases/`、`expected/` 與 `rules.json`（不複製、不產生 expected），比對器是 `tests/test_conformance.py` 的逐字移植，同樣套用 `case_overrides`。兩個執行器必須在同一個 commit 上都通過。TS 失敗先當成 TS 的錯；若審查發現是 Python 輸出違反 spec / contract，修 Python 並以 `--reason` 重新產生（CHANGELOG 註明 TS 的發現）；若不一致來自案例刻意坐落的 ulp 放大邊界，則經 `--rules-only` 加一筆 `case_overrides`，並在 `reason` 寫下實測的敏感度。兩條路都是有版本的 CHANGELOG 條目，沒有任何東西可以悄悄改。
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
