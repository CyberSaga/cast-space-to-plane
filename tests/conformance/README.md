# 一致性測試集（spec §7.5）

一致性測試集是 castplane 的**輸出合約**：固定一組場景輸入與對應的幾何輸出，任何實作（Python 參考實作、未來的 TypeScript 移植）都必須在規定的容差內重現這些輸出。擴充功能時先改測試集、再改實作；測試集的每一次變更都要記錄版本與原因。

## 位置

| 路徑 | 內容 |
| --- | --- |
| `cases/<案例>.json` | 輸入：一個 spec §4 格式的場景檔，外加一個說明用的 `description` 欄位（驗證時會被忽略，contract §2.0「未知鍵忽略」） |
| `expected/<案例>.json` | 輸出：`castplane.render(scene)["geometry"]` 經 `castplane.output.geometry_json.dumps` 寫出的 spec §6.2 幾何文件（contract §3.1 鍵、排序鍵、最短往返浮點數、結尾換行） |
| `CHANGELOG.md` | 版本紀錄：每次重新產生 expected 的日期、版本號、案例清單與原因 |
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

失敗訊息會列出案例名稱與不符的路徑（例如 `points.crate.v0.image[0]: expected …, got …`），最多列 25 條。

## 來源（目前版本 v2，見 `CHANGELOG.md`；共 34 個案例）

| 類別 | 案例 | 依據 |
| --- | --- | --- |
| 解析案例 | `analytic_unit_box_point_light_overhead`、`analytic_sun_45deg_box`、`analytic_sun_30deg_box`、`analytic_sphere_oblique_directional`、`analytic_camera_level`、`analytic_camera_pitched` | spec §7.2 四條 |
| 退化情況 | `degenerate_light_behind_viewer`（列 1）、`degenerate_light_parallel_to_picture_plane`（列 2）、`degenerate_directional_horizontal`（列 3）、`degenerate_vertex_above_point_light`（列 4）、`degenerate_point_behind_camera`（列 5）、`degenerate_face_parallel_to_light_point` / `_directional`（列 6）；另有 contract §2.3 / §2.6 / §2.7 的 `degenerate_light_below_receiver`、`degenerate_vertical_directional_light`（F 未定義）、`degenerate_light_at_camera_centre`（L′ 未定義）、`degenerate_light_inside_sphere`、`degenerate_cylinder_cap_at_light_height` | spec §5.7 每列至少一例 |
| 範例場景 | `example_basic`（spec §4 範例）、`example_construction_demo`、`example_curved_demo`、`example_three_point`、`example_directional` | `examples/*.json` |
| 凹多邊形 | `concave_prism_light_foot_in_notch`（光源垂足在 U 形稜柱的凹口內，由 `tests.reference.random_scenes.make_concavity_scene(1)` 凍結） | spec §7.3 |
| 部分埋入地面 | `buried_box_tilted`、`buried_cylinder_tilted`（曲面物件的地面截面鏈） | contract §2.3 / §2.6 |
| 相機 | `camera_roll_and_shift`、`camera_yaw_pitch_form` | contract §2.1 / §2.2 |
| 亂數場景 | `random_seed{0,3,9,14,23,38}_*objects`：`tests.reference.random_scenes.make_scene(seed, n_objects)` 產生、通過 §7.3 光線投射對照（IoU ≥ 0.99，含逐物件比對）後凍結；五種基元與兩種光源都有涵蓋 | spec §7.3 |

每個案例刻意只放少量物件，讓 expected 檔可以人工審閱；整組 expected 的大小必須 < 3 MB（測試會檢查）。

## 規則

1. **先加案例、再改實作。** 新功能或行為變更先寫進 `cases/`，用工具產生 expected，確認差異合理後才改程式。
2. **版本化。** expected 檔只能由 `tools/regen_conformance.py` 產生，不得手改（測試檢查檔案為 `geometry_json.dumps` 的標準形式）。工具強制要求 `--reason`，並在 `CHANGELOG.md` 追加一筆 `## v<N> — <日期>`：版本號、重新產生的案例清單、未變更的案例與原因。`v<N>` 就是測試集版本；每筆也記錄產生檔案的 Python / NumPy 版本。expected 檔只在該版本的直譯器／NumPy 上**位元相同**（別的 libm 會在少數葉節點的最後幾位有 ≈ 1e-12 的差異，容差比對仍全數通過）；`test_regen_tool_exit_codes_match_its_docstring` 只在 NumPy 版本與紀錄相同時要求 `--dry-run` 零差異，否則只要求每個有差異的案例仍通過上表的容差。
3. **TypeScript 移植必須全數通過**（spec §9、§10 M7）：移植版讀取 `cases/*.json`，產生同格式文件，依上表規則與 `expected/*.json` 比對。Python 為參考實作；兩邊不一致時先判定哪邊違反 spec / contract，再改測試集。
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
