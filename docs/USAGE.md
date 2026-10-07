# 使用說明：命令列與 API 參考

對應程式版本 `castplane 0.1.0`（M3）。概念與數學見 [`spec/spec-v0.1.md`](spec/spec-v0.1.md)，規範性的實作細節見 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 1. 命令列

```
castplane [--version] <command> ...
```

| 指令 | 用途 |
| --- | --- |
| `castplane render SCENE -o OUTDIR [選項]` | 渲染場景，寫出 `OUTDIR/<場景檔名>.svg` / `.json` / `.png` |
| `castplane validate SCENE [-q]` | 只驗證場景檔，印出物件、光源、受影面數量 |
| `castplane info SCENE [--camera JSON]` | 印出物件清單、畫布、主點、地平線 v_mm、三個消失點（軸平行畫面時印 `at infinity (axis parallel to the picture plane)`，表示該方向的線在畫面上仍平行）、L′、F′（在無窮遠時印 `at infinity, direction (…)`）、點／邊／影子／作圖線數量、自我驗證最大誤差、受影面清單（M4：有界／無界、平面、各光源的 `lit` / `casts`）與警告表 |
| `castplane stages SCENE [--camera JSON] [-o FILE] [-q]` | 把 A 段與 B 段的中間結果以標準 JSON（`{"A": …, "B": …}`）寫到 FILE 或 stdout，除錯與移植對照用 |
| `castplane import FILE [-o OUT.json] [--into SCENE] [--id ID] [-q] [網格選項]` | 把網格檔（OBJ、glTF / GLB、STL、PLY）匯入成場景檔（M5，見下方「`castplane import`」） |

`render` / `validate` / `stages` / `info` 都以 `castplane.io.load_expanded_scene` 讀場景：帶 `path` 的 `mesh` 物件先依場景檔所在目錄讀檔、展開成內嵌的 `data`，再做驗證（合約 §5.0.2）。展開時的匯入備註以 `note: <CODE> ['id', …]: message` 印到 stderr（`-q` 不印），**不會**寫進輸出文件的 `warnings`。

### `render` 選項

| 選項 | 說明 |
| --- | --- |
| `-o, --outdir DIR` | 必填；輸出目錄，不存在會建立 |
| `--camera JSON` | 相機覆寫：檔案內容可以是單獨的 `camera` 區塊（規格 §4 形式），或一個完整場景檔（取其 `camera`）。覆寫相機的 `frame_mm` 長寬比仍須等於場景 `output.canvas_mm` 的長寬比 |
| `--formats LIST` | 逗號分隔的 `svg,json,png` 子集，預設 `svg,json`。PNG 只在明確要求時才產生 |
| `--layers LIST` | 逗號分隔的圖層 id 子集（`horizon,objects,form_shadow,cast_shadow,construction,labels`），預設用場景的 `output.layers`；輸出順序永遠固定 |
| `--dpi N` | PNG 解析度，預設場景的 `output.png_dpi` |
| `-q, --quiet` | 成功時不印任何東西（不印輸出路徑、不印警告）；錯誤仍印到 stderr |
| `--hidden-lines` / `--no-hidden-lines` | M4：開／關取樣式消隱（預設用場景的 `output.hidden_lines`，預設關閉）；只傳給渲染器，不改寫場景（合約 §5.1.6.6） |
| `--hidden-style dashed\|omit` | M4：`dashed`（預設）把隱藏段畫成虛線放在各層第一個 `*.hidden` 子群組；`omit` 讓這些群組留空（真正的消隱，合約 §5.1.8） |

渲染的警告以 `warning: <CODE> ['id', …]: message` 寫到 stderr。

### 結束碼

| 碼 | 意義 |
| --- | --- |
| 0 | 成功 |
| 1 | 檔案錯誤（場景檔讀不到、輸出目錄寫不了） |
| 2 | 輸入無效：`SceneError`（訊息含 JSON 欄位路徑，例如 `error: objects[1].radius: must be > 0`）、`--formats` / `--layers` 有未知項目，或命令列用法錯誤（argparse 慣例） |
| 3 | 缺少選用相依套件：要求 PNG 但沒有 cairosvg 也沒有 resvg（`pip install 'castplane[png]'`）。此時**不寫任何檔案**，同一次要求的 SVG / JSON 也不寫。讀 STL / PLY 網格但沒有 trimesh（`pip install 'castplane[mesh]'`）也是 3 |

### 範例

```sh
castplane render examples/curved_demo.json -o out --formats svg,png --dpi 200
castplane render examples/basic.json -o out --camera examples/three_point.json --layers objects,cast_shadow
castplane info examples/directional.json
castplane stages examples/basic.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['B']['camera']['P'])"
castplane render examples/wall_and_ground.json -o out --hidden-lines              # M4：地面 + 牆面，隱藏線畫成虛線
castplane render examples/wall_and_ground.json -o out --hidden-lines --hidden-style omit
```

### `castplane import`（M5 網格匯入，合約 §5.0.2、§5.2.8）

```
castplane import FILE [-o OUT.json] [--into SCENE] [--id ID] [-q]
                 [--inline] [--node NAME|INDEX] [--camera NAME] [--light NAME]
                 [--scale S] [--weld TOL] [--smooth-angle DEG] [--up y|z]
```

依副檔名分派：`.obj` 用內建的 OBJ 解析器、`.gltf` / `.glb` 用內建的 glTF 2.0 讀取器、`.stl` / `.ply`（以及 trimesh 認得的其他格式）用選用的 trimesh（`pip install 'castplane[mesh]'`，只讀原始頂點與面，`process=False`）。寫出的是一個完整、可直接渲染的 spec §4 場景（`json.dumps(sort_keys=True, indent=1, ensure_ascii=False)`），寫出前先跑一次 `validate_scene` 當檢查。

| 選項 | 說明 |
| --- | --- |
| `-o, --output OUT.json` | 寫到這個檔（預設 stdout）；成功時印出路徑 |
| `--into SCENE` | 把匯入的物件**附加**到 SCENE 原本的 `objects` 之後，SCENE 的 `version` / `units` / `up` / `lights` / `receivers` / `camera` / `output` 與未知鍵逐字照抄（檔案裡的相機、光源此時不用）；SCENE 自己的網格物件若用相對 `path`，而 OUT 不在 SCENE 所在目錄，路徑改寫成相對於 OUT 所在目錄（stdout 時為目前目錄），寫出的場景因此一定能重新載入；匯入物件的 id 與 `ground` 或 SCENE 既有的物件／接收面 id 重複時加 `_2`、`_3`… |
| `--id ID` | 物件 id，預設為檔名主幹（`[A-Za-z0-9_-]` 以外的字元換成 `_`）；glTF 只在匯入結果恰好一個物件時可用（用 `--node` 選一個）；與 `ground` 或 SCENE 既有的 id 重複時是錯誤（結束碼 2），不會自動改名 |
| `--inline` | 把幾何以 `data` 內嵌進場景，而不是寫 `path` |
| `--node NAME\|INDEX` | 只匯入一個 glTF 節點（及其子樹）或一個 OBJ 的 `o` / `g` 名稱；全為數字時視為索引 |
| `--camera NAME` / `--light NAME` | glTF：用這個節點的相機／只保留這盞光 |
| `--scale S` | 檔案單位 → 公尺，寫成物件的 `scale`。在焊接**之前**套用：毫米檔要 `--scale 0.001`，否則預設 1e-6 m 的焊接容差等於 1e-9 檔案單位，接縫焊不起來 |
| `--weld TOL`、`--smooth-angle DEG` | 寫成物件的 `weld_tolerance`（公尺，預設 1e-6）與 `smooth_angle_deg`（預設 30） |
| `--up y\|z` | OBJ / STL / PLY 檔的上方軸（寫成物件的 `up`）；glTF 一律是 Y-up，給 `--up` 是用法錯誤 |
| `-q, --quiet` | 不印路徑與備註 |

輸出規則：網格物件以**相對於輸出檔所在目錄**的 POSIX 路徑引用 FILE（輸出到 stdout 時相對於目前目錄），或以 `--inline` 內嵌。OBJ / STL / PLY 匯入成一個 `mesh` 物件，相機與光源用預設值。glTF 的對應（合約 §5.2.8）：每個網格節點 → 一個 `mesh` 物件，`node` 寫節點名稱（名稱非空且在檔案中唯一時）否則寫節點索引，世界變換由載入器烘焙；節點的 `extras.castplane = {"type": "box" | "cylinder" | …, 參數}` → 該基元物件（參數為 castplane 局部慣例、公尺，局部 Z 朝上 = 節點局部 +Y，只接受均勻且為正的節點縮放）；透視相機 → `focal_length_mm = 12 / tan(yfov/2)`、片幅 `[24·aspectRatio, 24]`、畫布 `[240·aspectRatio, 240]`、`near_m = znear`、滾轉角由相機 up 向量求得；`KHR_lights_punctual` 的每一盞光都輸出（點光 → 點光、平行光 → 指向光源的方向、聚光燈 → 位置相同的點光）。沒有相機時用包圍盒預設相機（看向包圍盒中心、35 mm、36×24 片幅、360×240 畫布），沒有光源時用預設平行光 `[-0.5, -0.5, 0.7071067811865476]`（id `sun`）；受影面固定為地面。

匯入備註（`castplane.io.IMPORT_NOTE_CODES`；寫進場景的 `meta.import_notes` 並以 `note:` 印到 stderr，不是 §3 的警告）：

| 代碼 | 時機 |
| --- | --- |
| `IMPORT_SPOT_AS_POINT` | 聚光燈以點光匯入（ids：光源 id） |
| `IMPORT_CAMERA_DROPPED` | 檔案有多台相機，只用遍歷順序第一台（或 `--camera` 指定的）；ids：丟掉的相機節點 |
| `IMPORT_NO_CAMERA_DEFAULT` | 檔案沒有相機，用包圍盒預設相機 |
| `IMPORT_NO_LIGHT_DEFAULT` | 檔案沒有光源，用預設平行光 |

結束碼同上：0 成功；1 讀不到 FILE / SCENE 或寫不了輸出；2 `SceneError`（glTF 的錯誤欄位是 glTF JSON 路徑，例如 `error: nodes[3].scale: …`）、用法錯誤、或組好的場景驗證失敗（此時不寫檔）；3 缺 trimesh。在 M6 合併之前，場景驗證仍是 v1 的「恰好一盞光」，所以有兩盞以上光源的 glTF 要加 `--light NAME` 才能寫出。

```sh
castplane import tests/fixtures/meshes/box_split.obj -o scene.json
castplane import tests/fixtures/meshes/import_scene.gltf -o scene.json --light Lamp
castplane import tests/fixtures/meshes/box.glb --inline --into examples/basic.json -o with_box.json
castplane import tests/fixtures/meshes/features.obj --node walls --scale 0.5 -o walls.json
```

### 場景 JSON 的 `mesh` 物件（合約 §5.2.1）

| 鍵 | 規則 |
| --- | --- |
| `type` | `"mesh"` |
| `path` | 非空字串：網格檔路徑，相對路徑以場景檔所在目錄為準（給 dict 時以目前工作目錄為準）。只有 `path` 的物件必須先展開（`castplane.io.expand_scene` 或 CLI）；`castplane.load_scene` 對它回報 `objects[i].path`「mesh file must be expanded first」。展開後 `path` 原樣保留、只供參考 |
| `data` | 內嵌幾何 `{"vertices": [[x, y, z], …] (≥ 3), "faces": [[i, j, k, …], …] (≥ 1，每個 ≥ 3 個索引), "smooth_groups": [g, …] (選用，每面一個非負整數，0 = 無群組)}`。`path` 與 `data` 至少一個；兩者都有視為已展開（用 `data`） |
| `node` | 選用：字串或非負整數。glTF：深度優先遍歷中第一個同名節點（含子樹），找不到再找同名網格；整數為 `nodes[k]`。OBJ：`o` / `g` 名稱，整數為第 k 個不同名稱 |
| `up` | 選用：`"z"`（預設）或 `"y"`；`"y"` 以精確軸映射 `(x, y, z) ↦ (x, −z, y)` 轉成 Z-up。glTF 檔一律是 Y-up，配 `up` 是錯誤（`objects[i].up`） |
| `scale` | 選用：> 0，預設 1；乘在局部頂點上（檔案單位 → 公尺），在焊接之前 |
| `weld_tolerance` | 選用：≥ 0，預設 1e-6（公尺，縮放之後） |
| `smooth_angle_deg` | 選用：[0, 180]，預設 30；相鄰面法線夾角小於它（且平滑群組相同）的邊是平滑邊，只在成為相機輪廓時才畫 |
| `transform` | 同其他物件（`scale` 鍵不在 `transform` 裡，用物件的 `scale`） |
| 上限 | 面數、頂點數各 ≤ 50 000；焊接並移除退化面後至少要剩一個面（`objects[i].data.faces` / 檔案來源為 `objects[i].path`：「no usable face」） |

`mesh` 物件的 `edges[]` 多兩個鍵：`smooth`（與相機無關）與 `camera_silhouette`（與相機有關）。非流形網格（例如缺一個面）發 `MESH_NON_MANIFOLD` 並改用逐面影子（第 3 節）。

## 2. Python API

所有函式都是純函式：輸入是驗證過的場景 dict 與 numpy 陣列，輸出是可 JSON 序列化的資料（文件）或 numpy 陣列（中間結果）。公開進入點在 `castplane` 套件頂層；其餘模組依規格 §5 的符號命名，供測試、移植與進階使用。

### 2.1 頂層（`castplane`）

| 函式 | 說明 |
| --- | --- |
| `load_scene(path_or_dict) -> dict` | 讀取 JSON 檔或 dict，依合約 §2.0 驗證並回傳**新的**、填好預設值的場景 dict；失敗拋 `SceneError` |
| `validate_scene(scene) -> dict` | 同上，但只接受 dict |
| `shadow_geometry(scene) -> dict` | **A 段**：與相機無關的幾何——物件網格、光源向量 L、投影矩陣 M、垂足 F、受光旗標、光輪廓迴圈、齊次影子迴圈（含方向頂點）、影子點 S 與垂足 Q、曲面基元的輪廓圓與影子圓錐曲線、警告 |
| `project_scene(scene, A, camera=None) -> dict` | **B 段**：以場景相機或 `camera` 覆寫（規格 §4 形式的 dict）投影 A 段結果；相機矩陣、所有投影點與裁切後的線段／多邊形（齊次 2D）、L′、F′、作圖線、自我驗證 |
| `compose(scene, B) -> dict` | **C 段**：產生規格 §6.2 幾何文件（最後才除以 x̃₃、浮點數標準化、點名排序） |
| `render(scene, camera=None) -> dict` | 連跑 A、B、C 並寫 SVG：`{"geometry": doc, "svg": str}`，圖層子集取自 `scene["output"]["layers"]` |
| `SceneError(field, message)` | 輸入錯誤例外（`ValueError` 子類）；`field` 是 JSON 路徑 |
| `make_warning(code, ids=(), message=None) -> dict` | 建立 `{"code", "ids", "message"}` 警告；`code` 必須在 `errors.WARNING_CODES` 中 |
| `merge_warnings(*lists) -> list` | 合併警告清單，依 (code, ids) 去重並排序 |
| `__version__` | 版本字串 |

### 2.2 `castplane.scene` — 場景驗證

| 函式 | 說明 |
| --- | --- |
| `load_scene(path_or_dict) -> dict` | 見上 |
| `load_camera(path_or_dict) -> dict` | 讀取相機覆寫：檔案或 dict，內容是 `camera` 區塊或含 `camera` 的場景；回傳驗證過的相機 dict |
| `validate_scene(scene) -> dict` | 整份場景的驗證（合約 §2.0 表） |
| `validate_object(value, field) -> dict` | 一個 `objects[i]` 項目；`field` 是錯誤訊息用的路徑前綴 |
| `validate_transform(value, field) -> dict` | `transform` 區塊：選填、`scale` 不允許、補預設值 |
| `validate_light(value, field) -> dict` | 一個 `lights[i]` 項目（`id` 不含 `.`；平行光方向長度須為 1） |
| `validate_receiver(value, field) -> dict` | 一個 `receivers[i]` 項目（M4：任意平面、選填凸多邊形 `bounds`；無 bounds 的只能是 `receivers[0]` 的地面，由 `validate_scene` 檢查） |
| `validate_camera(value, field="camera") -> dict` | `camera` 區塊：target 形式或 yaw/pitch 形式，二擇一 |
| `validate_output(value, frame_mm, field="output") -> dict` | `output` 區塊：畫布長寬比須等於片幅長寬比（錯誤訊息列出兩個比值與可用的替代值）；`layers` 不得是空串列 |
| `polygon_signed_area(poly) -> float` | 鞋帶公式的有向面積，逆時針為正 |
| `polygon_is_simple(poly, eps_area, eps_len=None) -> bool` | 多邊形無自交（非相鄰邊不相觸） |
| `OBJECT_TYPES`、`LIGHT_TYPES`、`LAYER_IDS` | 允許的物件類型、光源類型、六個圖層 id（表格順序） |
| `validate_bounds(value, normal, offset, field) -> list` | M4：`receivers[i].bounds`（≥ 3 個世界座標點、在平面上、嚴格凸且簡單；順時針輸入靜默反轉成繞 n 逆時針，合約 §5.1.1） |
| `validate_hidden_output(o, field="output") -> dict` | M4：`output.hidden_lines`（布林，預設 false）與 `output.hidden_style`（`dashed` 預設 / `omit`） |
| `validate_receivers_in_scene(receivers, objects, lights)` | M4：受影面的場景層規則：id 唯一、不得與物件／光源 id 重複、保留字 `hidden`、無 bounds 只限 `receivers[0]` 的地面、有地面時 bounds 不得在地面以下 |
| `RESERVED_IDS`、`HIDDEN_STYLES` | M4：保留 id（`hidden`）與 `hidden_style` 的允許值 |

### 2.3 `castplane.errors` — 錯誤與警告

| 函式 | 說明 |
| --- | --- |
| `SceneError(field, message)` | 見上 |
| `WARNING_CODES` | 封閉的警告代碼表 `{代碼: 預設訊息}`（合約 §2.9 的 13 個代碼） |
| `make_warning(code, ids=(), message=None) -> dict` | 見上 |
| `merge_warnings(*lists) -> list` | 見上 |
| `warning_codes(warnings) -> set` | 警告清單中出現的代碼集合 |

### 2.4 `castplane.pipeline` — 三段管線

| 函式 | 說明 |
| --- | --- |
| `shadow_geometry(scene) -> dict` | A 段（見 2.1）。回傳 `{objects, vertices, bbox, scene_scale, tol, receiver, receivers, lights, shadows, warnings}`；M4：`receivers` 每個受影面一筆（平面、座標系、bounds 邊泛函、各光源紀錄、`lit` / `casts`），`shadows` 依受影面 → 光源 → 施影者排序 |
| `project_scene(scene, A, camera=None) -> dict` | B 段（見 2.1）。回傳 `{A, camera, scene_scale, tol, objects, lights, receiver_lights, receivers, plates, horizon, shadows, construction, warnings}`；M4：`B["A"]` 就是 A 段本身，`receiver_lights` 是非預設受影面的 F′_r，`plates` 是有界面的 bounds 點、邊與背光面 |
| `compose(scene, B, hidden_lines=None) -> dict` | C 段（見 2.1）；M4：`hidden_lines=None` 取場景 `output.hidden_lines`，文件頂層 `hidden_lines` 記錄實際值；另有 `receivers`、`construction.per_receiver` 等 M4 鍵（合約 §5.0.3） |
| `render(scene, camera=None, hidden_lines=None, hidden_style=None) -> dict` | 見 2.1；M4：兩個關鍵字覆寫場景的 `output` 值（場景本身不改） |

模組 docstring 記載點名規則、地面裁切與曲面物件的文件結構，是 §6.2 文件最完整的說明。

#### 文件是唯讀資料：與快取的 A 段共用串列

由同一個快取的 A 段（`A = shadow_geometry(scene)`）組出的每一份文件（`compose(scene, project_scene(scene, A, camera=...))`），其**與相機無關的串列是以參照共用的**：每個具名點的 `world` 座標串列、`shadows[].outline` / `loops` 的點名串列、`form_shadow[].faces` 的面名串列等，都是 A 段建好一次、直接放進每份文件的同一個 Python 物件（合約 §2.4 的 `world_lists` 等快取表；`castplane.pipeline` 模組 docstring）。與相機有關的內容（`image`、`depth`、所有可畫圖形、`back`、作圖線、自我驗證）每份文件各自新建。這是刻意的設計：只換相機重算（規格 §8 的 100 ms 路徑）靠的就是不重建這些串列。因此請把文件當成**唯讀**資料；要修改文件（例如平移世界座標、刪除迴圈）請先 `copy.deepcopy(doc)` 再改，否則會同時改到快取的 A 段與之後由它組出的每一份文件。`render()` 與命令列每次都建立新的 A 段，不受影響。

### 2.5 `castplane.camera` — 相機與裁切（規格 §5.4、合約 §2.2）

| 函式 | 說明 |
| --- | --- |
| `camera_forward(cam)` | 驗證過的相機 dict 的 `forward` 向量（target 形式或 yaw/pitch 形式） |
| `camera_matrix(cam, canvas) -> dict` | 相機紀錄 `{K, R, t, P (3×4), C, forward, near, s, u0, v0, canvas_mm, frame_mm, rect, warnings}`；`rect` 是外擴 25% 的畫布矩形 |
| `project(cam, X)` | x̃ = P·X，一個 4 向量或 (n, 4) 陣列 → 齊次 2D 3 向量 |
| `divide(x)` | (u, v) = (x̃₁/x̃₃, x̃₂/x̃₃)；繪圖管線的最後一步 |
| `nu(cam, X)` | 近平面泛函 ν(X) = forward·(x − C·w) − near·w |
| `depth(cam, X)` | 相機空間深度（[R \| t]·X 的第三分量） |
| `clip_segment_near(cam, A, B)` | 一條齊次世界線段對 ν ≥ 0 的近平面裁切 |
| `clip_segments_near(cam, A, B)` | 向量化版本，(m, 4) 陣列 → `(A′, B′, keep)` |
| `clip_polygon_near(cam, points)` | 齊次世界多邊形 (n, 4) 的 Sutherland–Hodgman 近平面裁切 |
| `rect_functionals(rect)` | 齊次矩形裁切的四個泛函，列 (a, b, c) 滿足 a·x̃₁ + b·x̃₂ + c·x̃₃ ≥ 0 |
| `clip_polygon_rect_h(points, rect)` | 2D 齊次多邊形 (n, 3) 對矩形的齊次裁切 |
| `clip_segments_rect_h(A, B, rect)` | 2D 齊次線段 (m, 3) 對矩形的向量化裁切 → `(A′, B′, keep)` |
| `project_polygons(cam, pts, lens)` | 批次版繪圖管線：填補（padded）的齊次世界多邊形一次走完近平面裁切、投影、矩形裁切與相除 |
| `clip_line_rect(line, rect)` | 2D 直線 a·u + b·v + c = 0 與矩形的交線段 `[[u, v], [u, v]]` 或 `None` |
| `vanishing_point(cam, d, tol=1e-9)` | 方向 (d, 0) 的影像 `[u, v]`，\|x̃₃\| ≤ tol 時為 `None` |
| `horizon(cam, tol=1e-9) -> dict` | 地面的地平線：`{line, v_mm, segment, vanishing_points: {x, y, z}}` |
| `UP_WORLD`、`FALLBACK_UP`、`RECT_GROW`、`TOL_DIR` | 世界上方向 (0,0,1)、相機沿 z 看時的替代 up (0,1,0)、畫布外擴比例 0.25、無因次容差 1e-9 |

### 2.6 `castplane.transform` — 物件變換（合約 §2.1）

| 函式 | 說明 |
| --- | --- |
| `rotation_x(deg)`、`rotation_y(deg)`、`rotation_z(deg)` | 繞 +X / +Y / +Z 的右手旋轉矩陣（度） |
| `euler_zyx_matrix(rotation_deg)` | R = Rz(rz)·Ry(ry)·Rx(rx)，`rotation_deg = [rx, ry, rz]` |
| `transform_frame(transform)` | 驗證過的 transform dict → `(R, position)` |
| `apply_transform(points, transform)` | world = R·local + position，(n, 3) 陣列 |
| `apply_rotation(vectors, transform)` | R·v，只旋轉不平移（方向、法線用） |

### 2.7 `castplane.mesh` — 內部網格表示（合約 §2.4）

網格是 dict：`vertices (n,3)`、`edges (m,2)`（每邊一次，i < j）、`faces`（外側看逆時針的頂點索引串列）、`face_normals (k,3)`、`edge_faces (m,2)`、`vertex_names`。

| 函式 | 說明 |
| --- | --- |
| `face_normals_newell(vertices, faces)` | Newell 法的外向單位法線（依面的頂點數分組向量化） |
| `mesh_from_faces(vertices, faces, vertex_names=None) -> dict` | 由頂點與逆時針面建立完整網格 dict |
| `box_mesh(size) -> dict` | 方塊 [−sx/2, sx/2] × [−sy/2, sy/2] × [0, sz] |
| `prism_mesh(polygon, height) -> dict` | 簡單逆時針多邊形沿 [0, height] 擠出的直稜柱 |
| `cylinder_mesh(radius, height, segments=32) -> dict` | 近似圓柱（n 邊形端面與側面四邊形；只供包圍盒與 M5 格式） |
| `cone_mesh(radius, height, segments=32) -> dict` | 近似圓錐（n 邊形底面、頂點 (0, 0, height)） |
| `sphere_mesh(radius, segments=32, rings=16) -> dict` | 近似 UV 球，球心 (0, 0, r) |
| `transform_mesh(mesh, R, position) -> dict` | 回傳頂點 R·v + position、法線旋轉後的新網格 |
| `mesh_bbox(mesh)` | `(min_xyz, max_xyz)` |
| `euler_characteristic(mesh) -> int` | V − E + F（封閉零虧格曲面為 2） |
| `CURVED_SEGMENTS`、`SPHERE_RINGS` | 近似網格的角向解析度 32、球的環數 16 |

### 2.8 `castplane.primitives` — 物件紀錄

| 函式 | 說明 |
| --- | --- |
| `build_object(obj) -> dict` | 驗證過的 `objects[i]` → `{id, type, mesh（世界座標）, point_names, analytic, bbox, frame, shape, face_first, faces_padded, face_lens, face_point_names, edge_templates, world_lists}`（後六個是批次 B 段必要的表，合約 §2.4）；曲面基元另帶 `analytic = {kind, base, axis, e1, e2, radius, height, centre}` |
| `point_inside_solid(rec, x, tol=0.0) -> bool` | 世界點 `x` 是否嚴格在多面體（box / prism）實體內超過 `tol`（在局部座標精確判定；曲面基元一律 False）；`LIGHT_INSIDE_OBJECT` 用 |
| `local_mesh(obj) -> dict` | 物件在局部座標的網格 |
| `analytic_record(obj, R, position)` | 曲面基元的世界座標解析參數；多面體為 `None` |
| `face_tables(mesh) -> dict` | `{face_first, faces_padded, face_lens}`：面的填補索引表（批次投影用） |
| `CURVED_TYPES` | `("cylinder", "sphere", "cone")` |

### 2.9 `castplane.light` — 光源與光輪廓（規格 §5.1）

| 函式 | 說明 |
| --- | --- |
| `light_vector(light) -> ndarray` | 齊次光源向量 L：點光 (x, y, z, 1)、平行光 (dx, dy, dz, 0) |
| `lit(n_f, p, L, tol=0.0) -> bool` | lit(f) ⇔ n_f·(l − w·p) > tol |
| `is_parallel(n_f, p, L, tol=0.0) -> bool` | 面在容差內與光線平行 |
| `lit_state(n_f, p, L, tol=0.0) -> (lit, parallel)` | 一個面的受光與平行狀態；parallel 蘊含 not lit |
| `face_lit_flags(mesh, L, tol=0.0) -> (lit, parallel)` | 向量化到整個網格的所有面 |
| `silhouette_edges(mesh, lit_flags) -> ndarray` | 光輪廓邊（相鄰兩面 lit 值不同）的索引 |
| `silhouette_loops(mesh, lit_flags) -> list[list[int]]` | 把光輪廓邊接成封閉頂點迴圈，從光源看受光面在左 |

### 2.10 `castplane.shadow` — 平面投影（規格 §5.2、§5.3）

| 函式 | 說明 |
| --- | --- |
| `shadow_matrix(pi, L) -> ndarray` | M = (πᵀL)·I₄ − L·πᵀ，S = M·P |
| `foot(pi, X) -> ndarray` | 沿平面法線的垂足 Q = (n·n)·X − (n·x + w·d)·(n, 0)；對 L 給 F |
| `shadow_w(pi, L, P)` | M·P 的 w 分量（≤ tol 表示頂點不低於光源） |
| `clip_loop_to_plane(points4, pi, tol=0.0, sources=None)` | 封閉齊次迴圈對 πᵀX ≥ 0 的 Sutherland–Hodgman 裁切（地面裁切的退路） |
| `clip_mesh_to_plane(mesh, pi, tol=0.0) -> (mesh, origins)` | 封閉網格被平面切成實體：平面正側的部分加上切面；`origins` 對應新頂點到原頂點或交點 |
| `shadow_loop(points4, M, pi, tol=0.0, tol_clip=None, frame=None, F=None) -> dict` | 一個光輪廓迴圈的影子多邊形：`{vertices (齊次，含方向頂點), sources, unbounded}`；M4：非地面受影面傳入 `frame` 與光源垂足 `F`（無窮遠弧在受影面座標系中繞 n 逆時針；地面 `frame=None` 保留 v2 算式） |
| `ARC_STEP_DEG` | 無窮遠弧每段最大角度 60° |
| `receiver_frame(n) -> (e1, e2)` | M4：受影面座標系，`e1 = normalize(z × n)`、`e2 = n × e1`（n 平行 z 時 `e1 = x`）；地面即 (x, y)（合約 §5.1.2） |
| `bounds_functionals(bounds, n) -> ndarray` | M4：有界面 bounds 的邊泛函 `ψ_k = (m_k, −m_k·b_k)`，`m_k` 為單位向內法線（合約 §5.1.2） |
| `clip_polygon_bounds(points4, sources, psi, bounds, tol) -> (points4, sources)` | M4：齊次影子多邊形（含方向頂點與無窮遠弧）對 bounds 的 Sutherland–Hodgman 裁切：帶狀容差、錨點規則、合併相鄰相等頂點、薄片視為空（合約 §5.1.3.3） |
| `plate_loop(bounds, pi, L, tol)` | M4：有界面當成施影板時的輪廓迴圈 `(loop4, vertex_ids)`：光在正側用儲存順序、負側反轉、側對光源（`|πᵀL| ≤ tol`）回傳 None |

### 2.11 `castplane.conics` — 圓錐曲線（規格 §5.6、合約 §2.6）

| 函式 | 說明 |
| --- | --- |
| `circle_matrix(rho) -> ndarray` | 局部座標 (x, y, 1) 的圓 C = diag(1, 1, −ρ²) |
| `embed_circle(centre, e1, e2) -> ndarray` | 圓平面到世界齊次座標的 4×3 嵌入 E = [e1 e2 c; 0 0 1] |
| `adjugate3(H) -> ndarray` | 3×3 伴隨矩陣（閉式） |
| `transform_conic(C, H) -> ndarray` | C′ = adj(H)ᵀ·C·adj(H)（H 奇異也不拋例外） |
| `ground_conic_map(M, E) -> ndarray` | 圓座標到地面 (x, y, w) 的 3×3 映射 |
| `normalize_conic(C) -> ndarray` | 對稱化並除以最大元素絕對值（使該元素為 +1） |
| `centred_conic(C, normalized=False)` | 平移到自身中心（拋物線平移到頂點）的圓錐曲線；`normalized=True` 表示輸入已 max-正規化，略過正規化 |
| `classify(C, tol=1e-12) -> str` | 平移不變的分類：`ellipse` / `parabola` / `hyperbola` / `degenerate` |
| `classify_and_condition(C, tol=1e-12, normalized=False) -> (kind, cond)` | 分類與條件數一次算出 |
| `condition_number(C) -> float` | 中心化後矩陣的 2-範數條件數 |
| `is_sampled(C, cond_max=1e8) -> bool` | `CONIC_SAMPLED` 判定：退化或條件數過大 |
| `ellipse_params(C)` | 實橢圓的 `(centre, (a, b), rotation)`；不是實橢圓時 `None` |
| `conic_point(H, theta, rho=1.0) -> ndarray` | 有理參數化 X(θ) = H·(ρ cos θ, ρ sin θ, 1) |
| `sample_arc(H, rho, theta0, theta1, n) -> ndarray` | θ0 到 θ1 等分 n 段的 (n+1, k) 齊次取樣點 |
| `sample_count(theta0, theta1, per_circle=64, minimum=8) -> int` | 取樣段數 max(minimum, round(per_circle·\|Δθ\|/2π)) |
| `functional_coeffs(f, H, rho=1.0) -> (A, B, C)` | 線性泛函沿參數化圓的係數：f·X(θ) = A cos θ + B sin θ + C |
| `sub_arcs_where_nonnegative(A, B, C, theta0=0, theta1=2π, tol=0) -> list` | A cos θ + B sin θ + C > tol 在 [θ0, θ1] 內的子弧（閉式） |
| `arc_svg_flags(centre, axes, rotation, p_start, p_mid, p_end) -> (large_arc, sweep)` | SVG `A` 指令旗標（以弧的中點判定） |
| `circle_frame(normal, tol=1e-9, fallback=None) -> (e1, e2)` | 輪廓圓座標系：e1 = normalize(n × z)（n ∥ z 時依序試 `fallback` 方向，預設世界 x），e2 = n × e1 |
| `circle_record(centre, e1, e2, radius) -> dict` | 圓紀錄 `{centre, e1, e2, radius}` |
| `circle_embedding(circle) -> ndarray` | 圓紀錄的 E（4×3） |
| `circle_point(circle, theta) -> ndarray` | 圓上的齊次世界點（w = 1） |
| `conic_entry(circle, H, arc=None, map="image") -> dict` | 合約 §3.1 的 `conics` 項目：`{conic, kind, arc, circle, map, sampled, cond}` |
| `ellipse_arc_params(H, rho, theta0, theta1)` | 弧在畫面上的橢圓參數與 SVG 旗標 `{centre, axes, rotation, start, end, large_arc, sweep}`；非實橢圓或取樣點在相機後方時 `None` |
| `TWO_PI`、`ARC_MIN_SPAN`、`SAMPLES_PER_CIRCLE`、`MIN_ARC_SAMPLES`、`COND_MAX`、`CLASSIFY_TOL` | 常數：2π、可忽略的弧長 1e-12、每圓 64 段、最少 8 段、條件數上限 1e8、分類容差 1e-12 |

### 2.12 `castplane.curved` — 曲面基元（規格 §5.6、合約 §2.6 / §2.7）

所有函式吃 `build_object` 的 `analytic` 紀錄與齊次 4 向量 L（光源**或**相機位置 (C, 1)，同一套程式）。

| 函式 | 說明 |
| --- | --- |
| `silhouette(analytic, L, tol=0.0) -> dict` | 對 L 的光輪廓：`{kind, lit_interval, theta_l, alpha, generators, arcs, cap_lit, loop, circle, cap_circles, light_inside, warnings}` |
| `terminator(analytic, L, tol=0.0) -> list` | 同一條輪廓的畫面側可畫項目（`form_shadow` 層）：`{"segment": (A4, B4)}` 與 `{"circle_arc": {...}}` |
| `shadow_outline(analytic, L, M, pi, tol=0.0, tol_dir=1e-9) -> dict` | 有向地面影子輪廓：圓錐曲線弧片段、母線影子線段、地面截面鏈、方向頂點；`{pieces, unbounded, warnings}` |
| `shadow_polygon_h(outline, samples_per_circle=64) -> dict` | 輪廓取樣成有向齊次地面多邊形 `{vertices, sources, unbounded}`（走一般繪圖管線） |
| `construction_points(analytic, L, tol=0.0, obj_id="obj") -> dict` | 作圖點 `{名稱: 4 向量}`：球 `c`、`sil.0..3`；圓柱 `g0/g1.base/top`；圓錐 `g0/g1.base`、`apex` |
| `camera_outline(analytic, C, tol=0.0) -> dict` | 從相機位置看的輪廓：`{generators, cap_arcs（含 back 旗標）, circle, camera_inside}` |
| `loop_pieces_4d(sil) -> list` | 輪廓迴圈拆成 4D 片段（線段、圓弧） |
| `canonical_light(L) -> ndarray` | L 的標準代表：有限點 w = +1、方向單位長 |
| `canonical_factor(L) -> float` | 使 L / s 為標準形的純量 s |
| `plane_min(analytic, pi) -> float` | 實體基元上 πᵀX 的最小值（精確曲面的 `OBJECT_BELOW_RECEIVER` 判定） |
| `stage_a_object(obj, lights, pi, tol, receiver_id, warnings) -> list` | 管線 A 段掛鉤：每個光源的輪廓、明暗交界線、作圖點與影子紀錄（存於 `obj["curved"]`） |
| `stage_b_object(obj, rec, cam, tol, warnings) -> None` | 管線 B 段掛鉤：相機輪廓、明暗交界線可畫項目、影子圓錐曲線弧與命名點，閉式近平面與畫布裁切 |
| `stage_b_objects(objs, recs, cam, tol, warnings) -> None` | 多個曲面物件一次做 B 段（規格 §8）：逐物件呼叫 `stage_b_object` 的批次版，所有物件的命名點與直線段合併成一次投影 |
| `arc_record(circle, theta0, theta1, full, T, cam, f_nu, rect_rows, map, which, back=False) -> dict \| None` | 一段圓弧經 H = P·T·E 的 B 段紀錄（含 `visible` 區間）；全在近平面後方時 `None` |
| `near_functional(cam) -> ndarray` | f_ν = (forward, −(forward·C + near))，滿足 f_ν·X = ν(X) |

### 2.13 `castplane.construction` — 作圖線（規格 §5.5、合約 §2.7）

| 函式 | 說明 |
| --- | --- |
| `special_point_image(cam, X, tol) -> dict` | L 或 F 的影像（直接相除、不裁切）：`{h, point, at_infinity, behind, undefined}` |
| `covering_segments(A, B, C)` | 每列三個共線 2D 點的涵蓋線段（遠點有限的作圖線） |
| `extended_segments(B, C, frac=0.2)` | B→C 向兩端各延伸 frac（遠點在無窮遠的作圖線） |
| `clip_segments_uv(segments, rect)` | (n, 2, 2) mm 線段的齊次矩形裁切 → `(clipped, keep)` |
| `self_check(Lp, Pp, Fp, Qp, Sp, tol)` | 自我驗證 S′_check = (L′×P′)×(F′×Q′) 對 S′，向量化 → `(誤差 mm, skipped)` |
| `coincidence_check(Sp, Rp, tol)` | L′ 或 F′ 未定義時的退化自我驗證（S′ = P′ 或 S′ = Q′） |
| `RAY_EXTENSION`、`LINE_ZERO_REL` | 延伸比例 0.2、直線視為零向量的相對門檻 1e-9 |

### 2.14 `castplane.homogeneous` — 齊次座標工具（合約 §2.8）

| 函式 | 說明 |
| --- | --- |
| `normalize_max(v)` | 除以最大分量絕對值，保留符號 |
| `row_max_abs(x)` | 沿最後一軸逐列取最大絕對值（逐欄計算，比短列的 reduce 快一個數量級） |
| `cross3(a, b)`、`join(a, b)`、`meet(a, b)` | 3 向量外積：兩點的連線／兩線的交點 |
| `to_homogeneous(points, w=1.0)` | (n, 3) → (n, 4) |
| `scene_scale(vertices, camera_position=None) -> float` | max(1, 頂點與相機位置包圍盒最長邊)；光源不計 |
| `tolerance(scale) -> float` | tol = 1e-9 × scale |
| `clip_segments_halfspace(a, b, fa, fb)` | 多條齊次線段對一個線性泛函 f ≥ 0 的裁切 |
| `clip_segment_halfspace(a, b, fa, fb)` | 單條版本；回傳 `(a2, b2)` 或 `None` |
| `clip_polygon_halfspace(points, values)` | 齊次多邊形對 f ≥ 0 的 Sutherland–Hodgman 一步 |
| `clip_polygons_halfspace(pts, lens, vals)` | 批次版（填補的多邊形陣列） |
| `TOL_DIR`、`ZERO_REL` | 無因次容差 1e-9、插值向量視為零向量的相對門檻 1e-12 |

### 2.15 `castplane.output` — 輸出

| 函式 | 說明 |
| --- | --- |
| `geometry_json.canonical(obj)` | 遞迴轉成 JSON 原生型別、浮點數 `x + 0.0`（去 −0.0）、numpy → Python |
| `geometry_json.dumps(doc) -> str` | 確定性的序列化：`json.dumps(canonical(doc), sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False)`；文件裡出現 NaN / Infinity 是合約違規（規格 §7.1 第 6 列），`dumps` 會丟出 `ValueError`，不會寫出 `NaN`（合約 §5.4.5，與 TypeScript 寫出器相同的失敗方式） |
| `geometry_json.write_geometry_json(doc, path)` | 寫檔（UTF-8、結尾換行） |
| `svg.write_svg(doc, layers=None, hidden_style="dashed") -> str` | 規格 §6.1 分圖層 SVG；`layers` 選子集，順序固定；未知 id 拋 `ValueError`；M4：`hidden_style`（`dashed` / `omit`）決定隱藏線子群組的畫法，`hidden_lines` 關閉的文件與 v2 輸出位元相同 |
| `svg.LAYER_ORDER`、`svg.STYLE` | 圖層順序與預設樣式屬性字串 |
| `svg.HIDDEN_STYLES`、`svg.HIDDEN_STROKE`、`svg.OUTLINE_STYLE` | M4：`hidden_style` 的允許值、各層 `*.hidden` 群組的線色（`#111` / `#335` / `#000`）、開啟消隱時影子輪廓群組 `cast_shadow.<light>.<object>.outline` 的描邊 |
| `png.write_png(svg_str, dpi=300) -> bytes` | 以 cairosvg（或 resvg）柵格化；沒有後端時拋 `ImportError` |
| `png.png_size(svg_str, dpi) -> (w_px, h_px)` | round(canvas_mm · dpi / 25.4) |

### 2.16 `castplane.cli`

| 函式 | 說明 |
| --- | --- |
| `main(argv=None) -> int` | 命令列進入點，回傳結束碼（見第 1 節） |
| `build_parser() -> ArgumentParser` | argparse 解析器 |
| `cmd_render(args)`、`cmd_validate(args)`、`cmd_stages(args)`、`cmd_info(args)` | 各子指令（`import` 在 `castplane.io.cli`） |
| `warning_table(warnings) -> str` | `info` 用的固定寬度警告表（code / ids / message） |
| `EXIT_OK`、`EXIT_IO`、`EXIT_INPUT`、`EXIT_MISSING_DEPENDENCY`、`FORMATS` | 結束碼 0 / 1 / 2 / 3 與可用格式 |

### 2.17 `castplane.hidden` — 取樣式消隱（合約 §5.1.6，M4）

C 段在 `hidden_lines` 開啟時呼叫；純 numpy、確定性（取樣位置只取決於畫出的圖形）。

| 函式 | 說明 |
| --- | --- |
| `classify_document(doc, A, B, cull=True) -> dict` | 填入 `edges[]`、外形母線、明暗交界線段的 `visibility` / `runs`，圓錐曲線的 `runs` / `hidden_polylines`（可見段之外的 `arcs` / `ellipses` / `polylines` 移除），以及 `shadows[].polygon_edges`；只指派新串列，不改 A、B。`cull=False` 關閉畫面矩形剔除（結果相同，測試用） |
| `occluder(rec) -> dict` | A 段物件或受影面紀錄的精確遮擋物：方塊、稜柱（側面四邊形 + 端面點包含，凹稜柱正確）、圓柱／圓錐、球、有界面（凸板）、無界地面（平面）；其他種類用通用封閉網格（有 `triangles` 用它，否則用 `mesh` 的面），永不拋例外 |
| `scene_occluders(A) -> list` | 所有物件 + 有界面 + `receivers[0]` 的無界地面 |
| `first_hit(occ, O, D, eps=HLR_RAY_EPS) -> ndarray` | 射線 `O + t D` 的第一個邊界交點參數 `t > eps`（沒有時為 `inf`） |
| `occluded(occs, C, X, eps, cam=None, bounds=None) -> ndarray` | 點 `X` 被隱藏：某遮擋物 `first_hit(C, X − C) < 1 − eps`；給 `bounds` 時做結果不變的剔除 |
| `image_bounds(occ, cam)` | 遮擋物外包點的投影矩形與最小深度 `(u_min, u_max, v_min, v_max, depth_min)`；地面或有點在近平面後方時為 `None`（不剔除） |
| `hlr_sample_count(length_mm) -> int` | `min(4096, max(8, ceil(ℓ/1 mm − 1e-9)))` |
| `hlr_tol_mm(length_mm) -> float` | 邊界容差 `max(1/64, ℓ/262144)` mm |
| `classify_curve(visible_at, p0, p1, length_mm)` | 一條曲線的中點取樣 + 固定 6 次二分：回傳 `(visibility, [(pa, pb, visible), ...])` |
| `drawn_segment_4d(cam, A4, B4)`、`drawn_segments_4d(cam, A4, B4)` | 畫出線段的 4D 端點：近平面裁切，再以 `P·X` 上的四個矩形泛函裁切（端點可為方向） |
| `clip_polygon_4d(cam, V4) -> (points4, ids)` | 影子多邊形的 4D 裁切路徑；`ids[j]` 是畫出邊 j 所在的原始邊，裁切產生的邊為 `None` |
| `runs_straight(result, a3, b3, length_mm)`、`runs_conic(interval, runs, cum, th)` | 文件的 run 紀錄：直線 `{s, t, mm, visible}`、圓錐曲線 `{interval, theta, mm, visible}` |
| `HLR_SPACING_MM`、`HLR_MIN_SAMPLES`、`HLR_MAX_SAMPLES`、`HLR_BISECTIONS`、`HLR_RAY_EPS` | 1.0、8、4096、6、1e-5（合約固定） |

### 2.17 M5 網格物件（`mesh`，合約 §5.2）

`castplane.scene` 新增（合約 §5.2.1、§5.0.1）：

| 函式 | 說明 |
| --- | --- |
| `read_json(path) -> dict` | 讀 JSON 檔；格式錯誤拋 `SceneError("", "invalid JSON: …")`（自 `load_scene` 抽出，供 `castplane.io.load_expanded_scene` 共用） |
| `validate_mesh_object(o, field) -> dict` | `validate_object` 的 `mesh` 分支：`data` 必填（只有 `path` 時回報 `objects[i].path`「必須先展開」）、`node` / `up` / `scale` / `weld_tolerance` / `smooth_angle_deg`、`up: "y"` 的精確軸映射、可用面檢查 |
| `validate_mesh_data(value, field, source_field=None) -> dict` | `objects[i].data`：`vertices`（≥ 3 個有限 `[x, y, z]`）、`faces`（≥ 1 個、每個 ≥ 3 個索引）、`smooth_groups`（預設全 0）、大小上限 |
| `to_z_up(vertices) -> list` | 精確軸映射 `(x, y, z) ↦ (x, −z, y)`（分量交換與變號，不用三角函數） |
| `AXIS_MAP`、`MESH_MAX_FACES`、`MESH_MAX_VERTICES`、`MESH_WELD_TOLERANCE_DEFAULT`、`MESH_SMOOTH_ANGLE_DEFAULT` | 軸映射矩陣、面數／頂點數上限（各 50 000）、預設焊接容差 1e-6 m 與平滑角 30° |

`castplane.primitives` 的 `prepared_mesh(obj) -> dict`：驗證過的 `mesh` 物件的前處理結果 `{mesh, triangles, fallback, smooth_groups, warnings, scale_A}`（局部座標）；`build_object` 在 mesh 紀錄上加 `triangles`、`fallback`、`smooth_groups`、`prep_warnings`，所有紀錄都有 `fallback`、`prep_warnings` 與 `mesh["edge_smooth"]`（基元全為 False）；`point_inside_solid` 對 mesh 用廣義纏繞數（退路網格沒有內部）。

`castplane.mesh` 的 `triangulate_faces(faces_padded, face_lens) -> (t, 3)`：填補面表的扇形三角化 `(f0, f_k, f_{k+1})`，以面為主序（合約 §5.2.3 第 4 步）。

`castplane.meshprep` — 網格前處理（核心模組，只用 numpy；合約 §5.2.3–§5.2.5）：

| 函式 | 說明 |
| --- | --- |
| `preprocess_mesh(data, scale, weld_tolerance, smooth_angle_deg, object_id="", return_scale=False)` | 整條前處理 → `(mesh, triangles, fallback, smooth_groups, warnings)`（`return_scale=True` 時多一項 `scale_A`）：縮放 → 焊接 → 退化面 → 鄰接／流形／方向 → 共面合併 → 邊分類；非流形時走逐面退路 |
| `has_usable_face(vertices, faces, scale, weld_tolerance) -> bool` | 驗證用的「至少一個可用面」檢查：在 `scale · vertices` 上焊接並移除退化面後是否還有面（合約 §5.2.1） |
| `mesh_scale(V) -> float` | `scale_A = max(1, 包圍盒最大邊長)`，本節所有容差的長度尺度 |
| `weld_map(V, tol, fast=True)`、`weld_vertices(V, faces, tol, fast=True)` | 焊接（27 鄰格、輸入索引最低的代表、取代表點原座標、依首次出現編號）；`fast` 為結果相同的向量化路徑 → `(W, faces_w, index)` |
| `prepare_faces(faces, index=None)` | 面轉成 int 串列並依 `index` 重新編號 |
| `drop_degenerate_faces(V, faces, scale_A)` | 折疊連續重複、丟掉頂點不兩兩相異或 Newell 法線 ≤ 1e-12·scale_A² 的面 → `(kept_faces, kept_index)` |
| `compact_vertices(V, faces)` | 移除沒有面用到的頂點（保持順序）→ `(V2, faces2, old_index)` |
| `triangulate(faces)` | 面串列的扇形三角化（`mesh.triangulate_faces`） |
| `build_adjacency(faces, n_v)` | 無向邊、每邊的相鄰面（不同的面索引）與走向、流形與一致性旗標 |
| `fix_orientation(faces, adjacency)` | 依 BFS 傳播修正繞向 → `(faces, flipped, components, conflict)` |
| `signed_volume(V, tris)`、`winding_number(V, tris, x)` | 依三角形順序逐項累加的有號體積與廣義纏繞數 |
| `point_inside_mesh(verts, tris, x, tol=0.0)` | `\|w\| > 0.75` 且到每個三角形的距離 `> tol` 才算在內部 |
| `merge_coplanar(V, faces, normals, adjacency, cos_tol)` | 依種子順序的區域生長共面合併 → `(new_faces, origin)` |
| `classify_edges(mesh, smooth_angle_deg, smooth_groups)` | 平滑邊／特徵邊（平滑群組不同即為特徵邊） |
| `fallback_mesh(V, faces, vertex_names=None)` | 非流形退路的 §2.4 形網格（`edge_faces = [f_min, f_max]`） |
| `inherit_edge_smooth(loop_mesh, origins, mesh, edge_smooth)` | 受影面切割後的網格繼承原始邊的平滑旗標（切面上的邊為特徵邊） |
| `COPLANAR_TOL_RAD`、`WELD_TOLERANCE_DEFAULT`、`SMOOTH_ANGLE_DEFAULT`、`MESH_MAX_RAYS`、`SMOOTH_BAND`、`INSIDE_WINDING` | 合約 §5.2.3 的常數（1e-3 rad、1e-6 m、30°、64、1e-9、0.75） |

警告代碼增加 `MESH_NON_MANIFOLD`、`MESH_WINDING_FIXED`、`MESH_DEGENERATE_FACES`、`MESH_RAYS_CAPPED`（合約 §5.0.5，接在 M4 的 `RECEIVER_UNLIT` 之後）。

### 2.18 `castplane.io` — 載入器與場景展開（只在 Python；合約 §5.0.2、§5.2.2、§5.2.8）

載入器只在「展開」這一步使用，`validate_scene` 與 A/B/C 段永遠只看內嵌的 `data`。

| 名稱 | 說明 |
| --- | --- |
| `load_expanded_scene(path_or_dict, base_dir=None) -> (scene, notes)` | `scene.read_json`（給路徑時）→ `expand_scene` → `validate_scene`；CLI 的 `render` / `validate` / `stages` / `info` / `import --into` 都用它。`base_dir` 預設為場景檔所在目錄，給 dict 時為目前工作目錄 |
| `expand_scene(scene, base_dir=None) -> (scene, notes)` | 回傳新的 dict：`EXPANDERS` 裡有的物件型別換成展開器回傳的物件（位置不變），其他元素深拷貝；對已展開的場景是冪等的；同一次呼叫內同一個檔案只解析一次 |
| `expand_mesh_object(obj, field, base_dir) -> (objects, notes)` | `EXPANDERS["mesh"]`：只處理有 `path`、沒有 `data` 的 `mesh` 物件，讀檔填入 `data`、保留原來的 `path` 字串；載入錯誤 → `SceneError(objects[i].path)`（節點找不到 → `objects[i].node`），glTF 配 `up` → `SceneError(objects[i].up)`，讀不到檔 → `OSError`（訊息含欄位路徑），缺 trimesh → `ImportError` |
| `load_mesh_file(path, node=None) -> raw` | 依副檔名（小寫）分派：`.obj` → `io.obj`、`.gltf` / `.glb` → `io.gltf`、其他 → `io.trimesh_adapter`；回傳 `{"vertices", "faces", "smooth_groups"}`（glTF 已轉 Z-up 並烘焙節點變換，其他為檔案原本的軸與單位） |
| `EXPANDERS`、`SUPPORTED_EXTENSIONS`、`IMPORT_NOTE_CODES` | 展開器登錄表（`{"mesh": expand_mesh_object}`；M8 加 `step`）、文件化的副檔名 `(".obj", ".gltf", ".glb", ".stl", ".ply")`、匯入備註代碼（`IMPORT_SPOT_AS_POINT`、`IMPORT_CAMERA_DROPPED`、`IMPORT_NO_CAMERA_DEFAULT`、`IMPORT_NO_LIGHT_DEFAULT` → 預設訊息）。備註 `{code, ids, message}` 不是 §3 的警告，永遠不會進文件的 `warnings` |

`castplane.io.obj`（純 stdlib）：

| 函式 | 說明 |
| --- | --- |
| `parse_obj(text) -> dict` | 解析 OBJ 文字：`v`、`f`（`v`、`v/vt`、`v//vn`、`v/vt/vn`、負的相對索引、≥ 3 個頂點的多邊形）、`o` / `g`、`s N` / `s off`、行尾 `\` 接續；`#`、`vt`、`vn`、`l`、`p`、`mtllib`、`usemtl` 與未知關鍵字略過。錯誤為 `SceneError("line N", …)` |
| `select_obj(parsed, node=None) -> raw` | 選取一個 `o` / `g` 名稱（字串）或第 k 個不同名稱（整數）的面；有選取時丟掉沒用到的頂點 |
| `read_obj(path)`、`load_obj(path, node=None, parsed=None)` | 讀檔後解析／選取 |

`castplane.io.gltf`（numpy + stdlib）：

| 函式 | 說明 |
| --- | --- |
| `read_gltf(path) -> (json, buffers)` | GLB 容器（`glTF` 魔數、版本 2、JSON 區塊與選用的 BIN 區塊）或 `.gltf`（base64 `data:` URI、相對於檔案的外部 `.bin`）；不支援的必要擴充（Draco、meshopt、量化）報錯 |
| `gltf_raw(doc, buffers, node=None) -> raw`、`load_gltf(path, node=None, parsed=None)` | 所有網格節點（或選取節點的子樹）的三角形：存取器支援 `byteStride` / `byteOffset`、POSITION 只接受 5126、索引 5121 / 5123 / 5125、模式 5 / 6 展開、0–3 略過；頂點乘世界矩陣（行列式 < 0 時反轉面）後做精確軸映射 `(x, y, z) ↦ (x, −z, y)`；帶 `extras.castplane` 基元的節點上的網格忽略 |
| `traversal_order(doc)`、`node_world_matrices(doc)` | 預設場景的深度優先遍歷順序（定義「第一個同名節點」）；每個節點的世界矩陣 `parent · T·R·S`（`matrix` 為行主序） |
| `euler_zyx(R) -> [rx, ry, rz]` | `R = Rz·Ry·Rx` 的分解（弧度；`hypot(R00, R10) ≤ 1e-12` 時 `rx = 0`） |
| `import_gltf_parts(path, *, ref=None, inline=False, node=None, camera=None, light=None, mesh_keys=None, parsed=None)` | 合約 §5.2.8 的對應表：網格節點 → `mesh` 物件（名稱唯一且非空時 `node` 寫名稱，否則寫索引）、`extras.castplane` → 基元物件、透視相機 → `camera` 區塊與畫布、`KHR_lights_punctual` 的每一盞光（聚光燈 → 點光並記 `IMPORT_SPOT_AS_POINT`）→ `({"objects", "lights", "camera", "canvas_mm", "raw"}, notes)` |
| `import_gltf_scene(path, *, ref=None, inline=False, node=None, camera=None, light=None, mesh_keys=None) -> (scene, notes)` | 同上再組成完整的原始場景：檔案沒有相機／光源時用包圍盒預設相機與預設平行光並記備註，受影面固定為地面 |

`castplane.io.trimesh_adapter`：`load_trimesh(path, node=None) -> raw` 用選用的 trimesh（`pip install 'castplane[mesh]'`）讀 STL / PLY 等格式，`trimesh.load(..., force="mesh", process=False)`，面與頂點照檔案儲存的順序（不合併、不修法線）；沒有 trimesh 時拋 `ImportError("install castplane[mesh]")`（CLI 結束碼 3）。

`castplane.io.cli`：`add_import_parser(sub)` 註冊 `import` 子指令、`cmd_import(args) -> int` 執行它（第 1 節）。

## 3. 警告代碼（合約 §2.9）

| 代碼 | 條件 | ids | 效果 |
| --- | --- | --- | --- |
| `CAMERA_LOOKING_ALONG_UP` | 相機視線平行世界 z | `[]` | 改用 (0, 1, 0) 當 up |
| `LIGHT_BEHIND_CAMERA` | 點光源的相機深度 < 0（平行光指向相機後方時 L′ 同樣是地平線下的反光點，但不發警告，D19） | `[光源]` | L′ 為有限的反光點 |
| `LIGHT_POINT_AT_INFINITY` | L′ 的 x̃₃ 在容差內為 0 | `[光源]` | `light_point` 為 null、`light_point_at_infinity` 給方向、作圖線平行 |
| `SHADOW_VP_AT_INFINITY` | F′ 的 x̃₃ 在容差內為 0 | `[光源]` | `shadow_vp` 為 null、`shadow_vp_at_infinity` 給方向 |
| `DIRECTIONAL_HORIZONTAL` | 平行光與受影面平行 | `[光源]` | 不輸出影子與作圖線 |
| `LIGHT_BELOW_RECEIVER` | 光源在受影面背側 | `[光源]` | 不輸出影子與作圖線 |
| `VERTEX_NOT_BELOW_LIGHT` | 某光輪廓頂點不低於點光源 | `[物件]` | 影子輪廓無界（方向頂點、`unbounded: true`） |
| `OBJECT_BELOW_RECEIVER` | 物件有部分在受影面下 | `[物件]` | 以地面切開後取地面以上部分的影子 |
| `POINT_BEHIND_CAMERA` | 某個要畫的點在近平面後方 | `[物件]` | `image` 為 null、線段裁切、該頂點不畫作圖線 |
| `FACE_PARALLEL_TO_LIGHT` | 某面（含圓柱、圓錐端面）與光線平行 | `[物件]` | 該面視為背光 |
| `LIGHT_INSIDE_OBJECT` | 點光源在球內、圓柱／圓錐完全無受光面，或嚴格在方塊／稜柱實體內 | `[物件]` | 該物件無影子、無明暗交界線、無作圖點（多面體的每個面都算背光，仍列在 `form_shadow`）；訊息指出種類 |
| `CONIC_SAMPLED` | 某圓錐曲線退化或條件數 > 1e8 | `[物件]` | 以取樣折線取代橢圓／弧 |
| `CONSTRUCTION_CHECK_SKIPPED` | 自我驗證的兩線其一為零向量、兩線平行或 S′ 在無窮遠 | `[點名]` | 該點不列入 `checks` |
| `RECEIVER_UNLIT` | M4：有界受影面收不到某光源（點光源在板的背側或板面上、平行光平行板面或從背側照來，或光源在無界地面之下——地面不透光）；唯一刻意的「資訊性」代碼（合約 §5.1.9） | `[光源, 受影面]` | 該板對該光源的影子紀錄存在但為空，`receivers[].lit[光源]` 為 false；板仍可對其他受影面投影 |
| `MESH_NON_MANIFOLD` | 某條邊不是恰好兩個相異面，或繞向不一致且無法以傳播修正（合約 §5.2.6） | `[物件]` | 逐面後備影子（§5.2.5）；不畫作圖線、不做 checks、不做光源在內判定 |
| `MESH_WINDING_FIXED` | 傳播翻轉了某些面，或某連通分量的有號體積正負號與其巢狀深度不符 | `[物件]` | 面已重新定向 |
| `MESH_DEGENERATE_FACES` | §5.2.3 第 3 步丟棄了退化面（訊息給數量） | `[物件]` | 忽略那些面 |
| `MESH_RAYS_CAPPED` | 同一（物件、光源、受影面）的特徵輪廓頂點超過 64 個 | `[物件]` | 只對迴圈順序的前 64 個畫作圖線、做 checks |

M4 改變的適用範圍（合約 §5.1.9）：`LIGHT_BELOW_RECEIVER`、`DIRECTIONAL_HORIZONTAL`、`VERTEX_NOT_BELOW_LIGHT`、`OBJECT_BELOW_RECEIVER` 只用於無界受影面（有界板的背後裁切是靜默的，裁切點命名為 `<物件>.s<k>.<光源>.<受影面>`）；`POINT_BEHIND_CAMERA` 的 ids 可以是受影面 id（其 `b<k>` 頂點或影子點）；`SHADOW_VP_AT_INFINITY` 對 `receivers[0]` 為 `[光源]`、其他受影面為 `[光源, 受影面]`；`CONSTRUCTION_CHECK_SKIPPED` 的點名帶受影面後綴。影子沒落在板上、物件在板後、板側對光源或相機、共平面施影體、以及任何消隱情況都**不**發警告。

以上四個 `MESH_*` 代碼由 M5 加入；合併後在警告清單中接在 M4 的 `RECEIVER_UNLIT` 之後（合約 §5.0.5）。
