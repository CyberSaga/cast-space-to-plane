# STEP 匯入：可行性報告與原型（M8）

對應規格 §9「STEP」列與 §10 M8（「可行性報告、原型解析器」）；規範性的細節是 [`ARCHITECTURE.md`](ARCHITECTURE.md) §5.5（以下「合約」），本文件說明為什麼這樣做、量到了什麼、還缺什麼。命令列與 API 見 [`USAGE.md`](USAGE.md) 的「`castplane import` 的 STEP 檔」與 §2.22。

## 1. 目的與結論

**目的。** 讓 CAD 軟體輸出的 STEP 檔（ISO 10303）直接成為 castplane 的場景物件：圓柱、球、圓錐、方塊這四種解析基元要以**參數化物件**進來（半徑、高度、位置、`rotation_deg`），而不是變成三角網格，因為投影幾何的價值——圓錐曲線影子、明暗交界線的生成線、作圖法的命名點——只有在參數化基元上才存在。

**結論（先寫）。**

1. **可行，而且不需要 OpenCascade。** 一個只靠標準函式庫的 Part 21 子集解析器（約 200 行）加上依面型簽章分類的辨識器（約 840 行，含單位、拓樸走訪、容差、組件檢查與 Euler 角分解），就能把 OCC 8.0 寫出的四種基元**逐位元**還原成 castplane 物件：`cylinder.step` 展開後的場景渲染出來的文件與 `examples/basic.json` 的渲染**逐位元相同**，也通過一致性比對 `expected/example_basic.json`。
2. **建議採路線 (b)**（無相依的 Part-21 子集解析器）作為主要路徑；路線 (a)（OCP）只用在兩個地方：不認得的實體的**網格化退路**（選用套件 `castplane[step]`），以及產生測試夾具的工具 `tools/make_step_fixtures.py`。
3. STEP 匯入是**載入器**（規格 §8「載入 … 為可選附加套件」）：在 `validate_scene` 之前把 `{"type": "step", "path": …}` 展開成一般物件，核心（`scene.py` 之後的一切）永遠看不到 STEP 檔或 OCP。因此 A 段仍與相機無關、文件仍可由（展開後的）場景 JSON 純幾何推導、TypeScript 移植不需要移植這一層、§8 的效能目標不受影響。
4. 狀態：**原型完成**（Part-21 解析器、四種基元、`castplane import`）；網格退路經 M5 的內嵌網格型別。一致性測試集不變（合約 §5.0.8）。

## 2. STEP 對解析曲面的表達

**標準與綱要。** AP203（組態控制設計）、AP214（汽車設計，OCC 預設寫 `AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }`）與 AP242（受管理的模型式 3D 工程）共用 ISO 10303-42 的幾何與拓樸實體；本原型只讀這些共用實體，所以三種綱要都適用。檔案格式是 ISO 10303-21（「Part 21」）的純文字交換結構：

```
ISO-10303-21;
HEADER; FILE_DESCRIPTION(…); FILE_NAME(…); FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }')); ENDSEC;
DATA;
#15 = MANIFOLD_SOLID_BREP('',#16);
#114 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );      ← 複合實體（complex entity）
…
ENDSEC;
END-ISO-10303-21;
```

值有六種：實體參照 `#n`、字串 `'…'`（`''` 跳脫）、列舉 `.T.` / `.MILLI.`、數字、`$`（未給）/ `*`（衍生），以及巢狀串列與型別值 `LENGTH_MEASURE(1.E-07)`。

**實體圖（以 OCC 實際寫出的 `tests/fixtures/step/cylinder.step` 為例）。**

```
MANIFOLD_SOLID_BREP #15
 └ CLOSED_SHELL #16 (#17, #105, #109)
    └ ADVANCED_FACE #17 (bounds, face_geometry #31, same_sense .T.)
       ├ face_geometry ∈ { PLANE, CYLINDRICAL_SURFACE #31 (placement #32, 300.), SPHERICAL_SURFACE, CONICAL_SURFACE }
       │   └ AXIS2_PLACEMENT_3D #32 (location #33 = (-1.5E+03, 6.E+03, 0.), axis #34 = (0., 0., 1.), ref_direction #35 = (1., 0., -0.))
       └ FACE_BOUND / FACE_OUTER_BOUND → EDGE_LOOP #19 (#20, #54, #77, #104)
           └ ORIENTED_EDGE #20 (*, *, edge #21, .F.)
              └ EDGE_CURVE #21 (start #22, end #22, geometry #24, .T.)
                 ├ VERTEX_POINT → CARTESIAN_POINT
                 └ geometry ∈ { CIRCLE #25 (placement, 300.), LINE, SURFACE_CURVE #24 / SEAM_CURVE #58 (curve_3d, pcurves…) }
```

OCC 把每個端面圓寫成 `SURFACE_CURVE`、把圓柱面的接縫寫成 `SEAM_CURVE`（兩者都帶參數曲線 `PCURVE`），讀取時取其 `curve_3d`。一個完整的球是**一個面**，邊界是一個 `VERTEX_LOOP`（只有一個頂點，沒有邊）。

**單位**是複合實體，由 `GLOBAL_UNIT_ASSIGNED_CONTEXT` 列出：

```
#114 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );
#115 = ( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) );
#116 = ( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() );
#117 = UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#114,'distance_accuracy_value','confusion accuracy');
```

角度單位為度時是 `CONVERSION_BASED_UNIT('DEGREE', #m)`，`#m = PLANE_ANGLE_MEASURE_WITH_UNIT(PLANE_ANGLE_MEASURE(0.0174532925199433), #弧度單位)`。

**數字精度的觀察。** OCC 寫方向用 12–13 位有效數字（`0.866025403784`、`2.775557561563E-17`），座標最多 14–15 位（`743.46242505348`）；圓錐半頂角寫成 `0.321750554397`（12 位）。所以由方向或角度**重建**的量只準到約 1e-12（相對），而直接寫出的頂點座標、半徑是精確的——辨識器因此盡量取頂點與半徑，見 §4。

**方塊對面共用同一法線方向，只靠 `same_sense` 區分。** OCC 為方塊兩個相對的面寫出**同一個** `PLANE` 軸方向：`box.step` 的 `#17` 與 `#137` 兩面的平面法線都是 `(0.866025403784, 0.5, 0.)`，差別只在 `ADVANCED_FACE` 的 `same_sense`（`.F.` / `.T.`）。也就是說，「平面的軸方向就是外法線」這個直覺在真實檔案裡不成立；本原型的辨識器因此**完全不讀任何正負號**（`same_sense`、迴圈方向、平面軸的正負），只用 `|n × a|`、`|n_i × n_j|` 與位置差（合約 §5.5.4「Sign-free reading」）。封閉實體具有規定的面型簽章就是該基元，外法線是隱含的。

## 3. 路線 (a)：OCP / pythonOCC

流程：`STEPControl_Reader()` → `ReadFile(path)`（回傳 `IFSelect_RetDone`）→ `TransferRoots()` → `OneShape()` → `TopExp_Explorer(shape, TopAbs_FACE)` → 每個面 `BRepAdaptor_Surface(face).GetType()` → `GeomAbs_Plane / Cylinder / Sphere / Cone` → `gp_Pln / gp_Cylinder / gp_Sphere / gp_Cone`（取位置、軸、半徑、半頂角）。

**安裝現實。**

- pythonocc-core 只有 conda 套件；cadquery-ocp（模組名 `OCP`）可以 `pip install`，這是唯一能放進 `pyproject.toml` 選用套件的途徑（`castplane[step] = cadquery-ocp>=7.7`）。
- wheel 67 MB、安裝後 158 MB；授權 LGPL-2.1。核心只能相依 numpy，所以 OCP 不可能是必要相依。
- **確定性只到 OCC 版本。** 數值結果（特別是網格化）隨 OCC 版本改變；就算同一版本，也要固定 `isInParallel = False` 才排除唯一的執行緒。
- **頂點重建誤差。** OCC 自己由 12 位的半頂角重建圓錐頂點：`gp_Cone.Apex()` 對 `cone.step` 給出 `(0, 0, 1.43e-9)`（相對於 1200 mm 的頂點高度誤差 1.4e-9 mm），而 Part 21 檔案裡頂點座標是精確寫出的 `(-2.E+03, 5.E+03, 1.2E+03)`。
- **OCP 8 的 API 名稱差異**（在 cadquery-ocp 8.0.1.1.0 驗證，7.7 也有）：要用 `TopoDS.Face(shape)`（`TopoDS.Face_s` 不存在）、`Bnd_Box.CornerMin()` / `CornerMax()`（`Get()` 不再解包）、`BRep_Tool.Triangulation_s`、`Interface_Static.CVal_s("xstep.cascade.unit")`（要在建立 reader **之後**讀，之前是 `''`，之後預設 `'MM'`）。

**評估。** (a) 讀得了幾乎所有 STEP，但它是 67 MB 的重相依、數值依 OCC 版本漂移，而且在我們最在意的地方（頂點）比直接讀檔案還不準。所以 (a) 不適合作主要解析器（合約 §5.5.11 (h)），但非常適合作「認不得就網格化」的退路與夾具產生器。

## 4. 路線 (b)：無相依的 Part-21 子集解析器

**語法層**（`castplane/io/part21.py`，純 stdlib，合約 §5.5.2）：一個帶具名群組的正規表示式依序比對 `skip`（空白與 `/* … */` 註解）、`ref`、`str`、`enum`、`real`、`name`、`punct`，註解在同一個詞法掃描中被吃掉，所以字串裡的 `'/*'` 不會被誤刪；數字以 Python `float()` 轉換（正確捨入、跨平台確定）。文法接受 HEADER、多個 DATA 區段、一般實體與複合實體、巢狀串列與型別值；重複的實體編號、截斷的檔案、使用者自訂實體 `!NAME`、二進位字面值都報 `Part21SyntaxError(offset, …)`。

**語意層**（`castplane/io/step.py`，stdlib + numpy，合約 §5.5.3–§5.5.7）：

- **單位**：唯一的換算是 `to_metres(x, unit_divisor) = float(x) / unit_divisor + 0.0`——**除法，絕不乘 0.001**。IEEE 除法正確捨入，所以每個可精確表示的 mm 值（整數、二進位分數）除以 1000 正好是公尺字面值的 double（`300./1000. == 0.3`、`9./1000. == 0.009`），而 `9*0.001 = 0.009000000000000001`；`[−10000, 10000]` 的整數中有 2676 個用乘法會差一個 ulp。只接受 mm 與 m；沒宣告長度單位時假設 mm 並記備註。
- **拓樸走訪**：實體 = 每個 `MANIFOLD_SOLID_BREP`（依實體編號）；OCC 把多實體複合寫成**組件**，只接受恆等的 `ITEM_DEFINED_TRANSFORMATION`。
- **容差**：每個檔案算一次、以 mm 計：`tol = 1e-6 · max(1 mm, 最大座標)`（換回檔案單位），方向判斷 `1e-7`。容差只用來**分類**，輸出的幾何一律取自檔案的精確數字與重新正交化的座標框，不會漏進場景。
- **四個辨識器**：圓柱（圓柱面同軸同半徑 + 恰好兩個垂直於軸的平面；軸朝上正規化，`ref_direction` 保留）、球（全部是同心同半徑的球面；一律用恆等座標框，錨點在底部）、圓錐（圓錐面 + 恰好一個平面；**頂點取自拓樸頂點**而不是由半頂角重建，因此高度精確；再檢查表面半徑在頂點處為零）、方塊（6 個平面依法線分 3 組、互相垂直、8 個不同頂點）。旋轉以 `euler_zyx_deg(R)` 分解（先把九個元素 `+ 0.0` 去掉 `-0.`，角度落在 `(−180°, 180°]`）。

**量測**（`benchmarks/README.md` 的 M8 節）：夾具的 `import_step` 每個 0.45–4.1 ms（最小值；`box.step` 350 個實體最慢），其中約 85 % 是 Part 21 解析；200 個 OCC 圓柱的組件（`python tools/make_step_fixtures.py --bench-solids 200` 產生，1.24 MB、24 220 個實體）0.31–0.40 s（原型量測 1.25 MB、0.63 s）。程式量：`part21.py` 約 200 行、`step.py` 約 840 行（原估約 700 行；多出來的是錯誤訊息、組件與單位的邊界情況、網格化退路與 Euler 分解的符號零處理）。

## 5. 建議與工作量

**建議：路線 (b) 為原型與主要路徑；(a) 只作網格退路與夾具產生器。**

| 工作 | 估計 | 實際 |
| --- | --- | --- |
| (b) Part 21 解析器 | 1 天 | 完成（`part21.py`） |
| (b) 單位、拓樸、四個辨識器 | 1.5 天 | 完成（`step.py`；審查後重寫了方塊的無正負號規則、圓錐的頂點檢查與萬向鎖的符號零） |
| CLI 與場景展開（`EXPANDERS["step"]`、`castplane import` 的 STEP 選項） | 0.5 天 | 完成 |
| 夾具與測試（8 個夾具、`tests/test_step.py`） | 1 天 | 完成 |
| 文件（本文件、USAGE、README、基準） | 0.5 天 | 完成 |
| (a) 網格退路與夾具產生器（OCP） | 0.5 天 | 完成（`tessellate_step`、`tools/make_step_fixtures.py`） |

## 6. 範圍外與錯誤／備註清單

**範圍外**（報 `StepError … unsupported`，或在 `fallback: "mesh"` 時網格化）：

- B-spline 曲面（`B_SPLINE_SURFACE_WITH_KNOTS` 等）、環面（`TOROIDAL_SURFACE`）、掃掠面（`SURFACE_OF_REVOLUTION`、`SURFACE_OF_LINEAR_EXTRUSION`）；
- **截頭圓錐**（兩個平面；castplane 的 `cone` 型別沒有截頭）、有鍵槽或倒角的圓柱、傾斜端面；
- **組件變換**：非恆等的 `ITEM_DEFINED_TRANSFORMATION` 與任何 `MAPPED_ITEM`（串接多層放置是第一個後續工作）；
- mm / m 以外的長度單位（inch、foot、cm…）、同一檔案兩個不同的長度單位；
- `BREP_WITH_VOIDS`、`FACETED_BREP`、`SHELL_BASED_SURFACE_MODEL` 等非 `MANIFOLD_SOLID_BREP` 的實體（沒有任何 `MANIFOLD_SOLID_BREP` 時，錯誤訊息列出找到的種類與數量）。

**錯誤**：`StepError(field, message)` 是 `SceneError` 的子類別，多一個屬性 `entity`（`"#15"` 或 `None`）；展開場景時 `field` 是 `objects[i].path`，單獨呼叫 `import_step` 時是給的 `field`（預設 `"step"`）；訊息以實體編號（`#15: unsupported solid: faces {CONICAL_SURFACE: 1, PLANE: 2} (supported: cylinder, sphere, cone, box)`）、`syntax:`（附 `at offset N`）或 `unsupported:` 開頭。CLI 結束碼 2；讀不到檔是 `OSError`（1）；`fallback: "mesh"` 缺 OCP 是 `ImportError`（3）。

**備註**（`castplane.io.step.STEP_WARNING_CODES`，也是 `castplane.io.IMPORT_NOTE_CODES` 的子清單；永遠不進文件的 `warnings`）：`STEP_UNIT_ASSUMED_MM`、`STEP_ANGLE_UNIT_ASSUMED_RAD`、`STEP_SOLID_TESSELLATED`（ids 為實體編號）。

## 7. 與 M5 的介面與相依

規格 §10 把 M5 列為 M8 的前置。解析路徑（§4）其實不依賴 M5；**網格退路**依賴：OCP 網格化的結果經 `mesh_object_from_triangles` 變成 M5 的**內嵌 `data` 網格物件**（`{"vertices": 公尺、未焊接, "faces": 0 起算、向外繞向, "smooth_groups": 全 0}`），交給 M5 的前處理管線（焊接 1e-6 m 把逐面的接縫接起來、流形檢查、共面合併、邊分類）。

- `type: "step"` → **解析辨識**（唯一的解析路徑），認不得時依 `fallback` 報錯或網格化；
- `type: "mesh"` + `path` 結尾 `.step` / `.stp`（不分大小寫）→ **直接網格化**，不做辨識；
- 兩者經同一套登錄表：`castplane.io.EXPANDERS = {"step": expand_step_object, "mesh": expand_mesh_object}`、`castplane.io.EXTENSION_LOADERS = {".step": tessellate_step, ".stp": tessellate_step}`（`load_mesh_file` 先查它），以及同一個 `castplane import` 子指令（STEP 選項 `--solid`、`--fallback`，與網格選項互斥）。

網格化實測（cadquery-ocp 8.0.1.1.0，合約 §5.5.7 的偏差規則 `max(0.01, 1e-3 · 包圍盒對角線)` mm，只記錄、不斷言）：圓柱 170 節點 / 164 三角形、截頭圓錐 400 / 598、方塊 24 / 12、球 1447 / 2836。

## 8. 驗收案例

`tests/test_step.py`（合約 §5.5.10）。主要的幾條：

- **圓柱逐位元**：`{"id": "pillar", "type": "step", "path": "cylinder.step"}` 展開後**完全等於** `{"id": "pillar", "type": "cylinder", "radius": 0.3, "height": 2.4, "transform": {"position": [-1.5, 6.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}`；`examples/basic.json` 的 `pillar` 換成這個 step 物件，經 `castplane.io.load_expanded_scene` + `render` 得到的文件，其 `geometry_json.dumps` 與內嵌版**逐位元相同**，且通過 `compare_documents` 對 `expected/example_basic.json`。
- **手算數字**（閉式、不用 castplane 程式碼）：`b = (−1.5, 6, 0)`、燈 `l = (0, 3, 3.5)`、`r = 0.3`、`h = 2.4`；`d = √11.25 = 3.3541019662496847`、`θ_l = atan2(−3, 1.5) = −63.43494882292201°`、`α = acos(r/d) = 84.86845205068873°`；`pillar.g0.base = (−1.7552526894158411, 5.8423736552920795, 0)`、`pillar.g1.base = (−1.220747310584159, 6.10962634470792, 0)`；`S = l + (P − l)·35/11` → `pillar.g0.top.shadow.lamp = (−5.584894920868585, 12.043916175929343, 0)`、`pillar.g1.top.shadow.lamp = (−3.884195988222324, 12.894265642252474, 0)`；測試在 1e-9 m 內斷言。
- 單位算術（`9 mm → 0.009`、`1001 mm → 1.001`、`0.5 mm → 0.0005`，乘法都會錯）、`sphere.step` / `cone.step` 精確相等、`box.step` 在 1e-9 內並通過 `example_basic` 比對、`cylinder_down.step` 為 `[0, 0, 180]`（文件只在圓錐曲線的座標框與參數上不同，共 64 個葉節點）、`cylinder_tilted.step` 通過 `expected/buried_cylinder_tilted.json`、`frustum.step` 的錯誤與網格退路、`two_solids.step` 的 id 與 `solid` 選取、CLI 各情況、`import_step` 三次取最小值 < 500 ms。

## 9. 風險

- **Exporter 精度**：其他系統可能只寫 9–10 位有效數字。方向判斷的 1e-7 容差涵蓋 ≥ 9 位的 exporter；更低的精度會讓基元被判為不支援（安全的失敗方向：報錯或網格化，不會產生錯的基元）。
- **分割面**：有些系統把圓柱側面切成兩半、把球切成多片。辨識器已接受多個同軸同半徑的圓柱面與多片同心球面，但切法若引入額外的平面（例如分割用的平面面片）就會被判為不支援。
- **單位宣告缺失**：沒有單位時假設 mm 並記 `STEP_UNIT_ASSUMED_MM`；若檔案其實是公尺，物件會小 1000 倍——備註是唯一的提示。
- **OCC 版本漂移**：網格退路與夾具產生器的輸出依 OCC 版本；解析路徑只讀檔案位元，不受影響。夾具以 cadquery-ocp 8.0.1.1.0 寫出並提交，`tools/make_step_fixtures.py --check` 只在同一版本時要求逐位元相同。
- **PRODUCT 名稱的程序計數器**：OCC 在 `PRODUCT` 名稱裡寫入每個程序遞增的計數器（`'Open CASCADE STEP translator 8.0 8.1'`），同一組夾具在不同的寫出順序下位元組不同；產生器因此固定寫出順序並把名稱改寫成 `'castplane <fixture>'`。STEP 的產品名稱從不當作物件 id。
- **網格退路與損壞的檔案**：OCC（cadquery-ocp 8.0.1.1.0）在轉換時遇到無法解析的參照會直接讓直譯器崩潰（segmentation fault，無法以例外攔截）。`import_step(fallback="mesh")` 因此在呼叫 OCP 之前檢查要轉換的紀錄（單一實體檔為整個檔案、多實體檔為該實體可達的紀錄）：每個 `#n` 參照都必須指向已定義且編號不為 0 的實體，否則回報 `StepError`。**已知限制**：參照指向**型別錯誤**的實體，或必須是參照的位置寫成數字、`$`、列舉值（例如 `LINE('',#74,#74)`，`#74` 是 `VECTOR`），仍可能讓 OCC 崩潰；要擋下這類檔案需要 ISO 10303-42 綱要或在子程序裡執行 OCP。來源不明的 STEP 檔若要使用網格退路，請在獨立的程序裡執行 `castplane import`。
- **Euler 角的 libm 依賴**：旋轉過的實體的 `rotation_deg` 經 `atan2`，最後一位依 libm 而定（與一致性 expected 檔同樣的「每個建置確定」規則）；未旋轉的實體在任何平台都逐位元相同。
