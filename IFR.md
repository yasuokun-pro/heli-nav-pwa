# IFRモード 設計メモ(2026-09-13 起草・未着手)

**この文書は、どのセッション・どのモデルからでも作業を再開できるように書いてある。**
まず「4. 進め方」の Stage 1 から。判断済みの事項は「6. 決めたこと」にある。

## 1. やりたいこと(要望の原文に沿って)

1. 機体プロファイルを設定: 搭載無線機、航法装置(VOR/DME/ILS/GNSS…)、燃料、与圧の有無
2. 出発・目的・代替飛行場を選ぶ
3. 装備から**使える出発方式(SID)・進入方式(IAP)・経路・高度・最低気象条件**を自動で見繕い、
   ログを作ってルートを引く
4. そのあと **FIX / SID / STAR / 進入方式を手で差し替え**られる(微修正)

要望にあった動画プレイリスト(YouTube)は**Claudeからは見られない**。出発方式・着陸方式の
根拠はすべてAIP(AD 2.22 / AD 2.24 / ENR 3 / ENR 4.3)から取る。

## 2. データの棚卸し(2026-09-13 に実測。AIRAC 20260709)

置き場: `~/Downloads/AIP File Download Service/1_AIP (PDF)/20260709/`
`enr.txt` は `pdftotext -layout ENR_20260709.pdf` の出力(4.5MB)。行番号はその中の位置。

| 出典 | 中身 | 量 | 取りやすさ |
|---|---|---|---|
| **ENR 4.3** (39651行〜51404行) | 重要地点=FIX の名前と座標。▲=義務位置通報点 △=任意 | **約1,900点** | ◎ 表。ただし**名前と座標が別の行**に割れる(ACAの座標表と同じ癖) |
| **ENR 4.1** | VOR/DME/TACAN/NDB | 129 | ◎ **既に取得済み** (`tools/gen_navaids.py` → `navaids.gen.js`) |
| **ENR 3.1** (10362行〜13957行) | 下層ATSルート(A/B/G/R/V/W) FIX列・磁方位・距離・MEA・高度方向 | **70本** | ○ 表。列が縦に散るので状態機械で読む |
| **ENR 3.3** (13968行〜31361行) | RNAV経路(Y/Z) 同上+航法仕様(RNAV5等)・MOCA・DME要件 | **261本** | ○ 同上。**主力の経路はほぼこちら** |
| **ENR 3.4** | ヘリコプター経路 | **Nil** | — AIPにヘリ専用IFR経路は無い |
| **AD 2.24 索引** (各飛行場PDFの "CHARTS RELATED TO AN AERODROME" ページ) | SID/STAR/IAC の**名前と種別の一覧** | 113空港 / **SID 418・STAR 193・IAC 665** | ◎ 本文レイヤの1行1図。`grep "Standard Departure Chart\|Standard Arrival Chart\|Instrument Approach Chart"` で取れる |
| **AD 2.22** | 飛行方式(文章)。離陸最低気象条件など | 各空港 | △ 英文の散文。必要な数字だけ正規表現 |
| **AD 2.24 各図**(SID/STAR/IAC本体) | 経路の**形**、DA/MDA、RVR、MAP | 1,276枚 | ✕ **図。福岡TCAと同じ図の読み取り仕事**。全国は現実的でない |

⚠ IACのミニマ欄(DA/RVR)が本文レイヤから取れるかは**未確認**(Stage 1 で最初に確かめる。
`pdftotext -layout` で IAC のページを1枚出して DA/MDA/RVR の数字が文字で出るか見る。
索引ページ(RJTTならAD2-81)は図ではないので間違えないこと)。

## 3. 装備で決まること(ルールの骨子)

| 装備 | 効くところ |
|---|---|
| GNSS 無し | RNAV SID/STAR、RNP APCH、Y/Zルート(RNAV5以上)が**全部使えない**。V/W/A/G ルートと VOR/ILS/NDB 進入だけ |
| ILS 受信機無し | ILS/LOC/LDA/GLS 進入不可。VOR/NDB/RNP のみ |
| VOR 無し | VOR進入・VORルート不可 |
| DME 無し | DME要件のあるルート区間(ENR 3.3 の "DME required")不可、DMEアーク進入不可 |
| **与圧無し** | 巡航高度の上限(酸素の規定)。**まずは 10,000ft(FL100)を上限**にして設定で変えられるように |
| 燃料 | 航続 → 代替まで届くか。ログの燃料欄と連動 |
| 無線機 | 周波数帯(VHF/UHF)で管制との交信可否。当面は表示だけ |

最低気象条件:
- 離陸: AD 2.22 の Take-off minima(文章)。無ければ国の標準
- 着陸: 進入方式ごとの DA/MDA・RVR(**図から**。上記の未確認事項)
- 代替: 進入方式の種類で決まる標準(精密/非精密/なし)。ルールとして持つ

## 4. 進め方(段階。上ほど確実で安い)

### Stage 1 — 表から取れるデータで土台を作る(図は読まない)
1. `tools/gen_fix.py` : ENR 4.3 → `fix.json`(名前・座標・義務/任意・ATSルート名)。
   ⚠ 名前と座標が別行。`▲/△` の記号行、カナ行が挟まる。ACAの座標表パーサ
   (`tools/gen_aca.py` の `dms()`)を流用
2. `tools/gen_awy.py` : ENR 3.1 + 3.3 → `awy.json`(ルート名・FIX列・区間ごとの
   磁方位/距離/MEA/MOCA/高度方向/航法仕様/DME要件/管制機関)。
   ⚠ 列が縦に散るので「FIX名の行を見つけたら、次のFIXまでの間の数字を区間の属性として拾う」
3. `tools/gen_proc.py` : 全 AD2 PDF の AD 2.24 索引 → `proc.json`
   (ICAO・種別 SID/STAR/IAC・名前・RNAVか否か・進入の種類 ILS/LOC/LDA/VOR/NDB/RNP/GLS・RWY)。
   **これだけで「装備で使える方式の一覧」は出せる**
4. IACのミニマが本文レイヤから取れるか確認 → 取れれば `proc.json` に DA/MDA/RVR を足す
5. 地図: **FIXレイヤー**(`fix.json`)と**航空路レイヤー**(`awy.json`)を追加。
   既存の NAV レイヤー(navaids)と同じ作法(`地物` グループ)。FIXは名前つきの小さな三角、
   航空路は細い線+ラベル。ズームで間引く(障害物レイヤーと同じ「画面内だけ描く」)

### Stage 2 — 計画ロジック(データが揃えば純粋にJS)
1. 機体プロファイル(設定画面。`hnav.acft` に保存)
2. 出発/目的/代替の選択(既存の飛行場検索を流用)
3. **経路探索**: FIX+航空路をグラフにして Dijkstra。装備で使えない経路を外す。
   出発空港近くの FIX(SIDの終点)から目的空港近くの FIX(STARの始点)まで
4. **高度**: 区間の MEA/MOCA の最大以上、与圧無しなら上限、方向による奇偶(ENR 3 の
   Odd/Even 列)。IFR巡航高度の規則
5. SID/STAR/進入の候補提示(装備でフィルタ)→ 既定を自動選択、手で差し替え可
6. 最低気象条件の判定と METAR/TAF との突き合わせ(METAR は既にある)
7. ログ生成(既存のログ機能へ流し込む)、ルート描画(既存の wps に落とす)

### Stage 3 — 方式の形(図の読み取り。必要な空港だけ)
- SID/STAR/IAC の実際の経路を図から起こす。福岡TCAでやった
  「pdftocairo -svg → 線幅で仕分け → polygonize」の応用。線ではなく**経路(折れ線)**を追う
- **全国はやらない**。ユーザーの使う空港から順に(まず出発・目的で選ばれた空港)

## 5. データモデル(案)

```
fix.json  { eff, f:[ {n:"ABASA", lat, lng, c:1(義務)|0, rt:["Y10",…] } ] }
awy.json  { eff, f:[ {n:"Y10", spec:"RNAV5", sens:["GNSS","DME/DME"],
                       seg:[ {a:"LUMIN", b:"WKE", mag:194, dist:20.6,
                              mea:"FL200", moca:3000, up:"UNL", dir:"↓奇数↑偶数",
                              dme:"RSE<2.0nm…", unit:"Fukuoka ACC 133.3"} ] } ] }
proc.json { eff, f:[ {icao:"RJTT", k:"SID"|"STAR"|"IAC", n:"VAMOS FOUR DEPARTURE",
                       rnav:true, typ:"ILS"|"LOC"|"LDA"|"VOR"|"NDB"|"RNP"|"GLS"|null,
                       rwy:"34L"|null, page:81 } ] }
hnav.acft { gnss:true, ils:true, vor:true, dme:true, ndb:false, press:false,
            maxAlt:10000, fuelKg, burnKgH, vhf:true, uhf:false }
```

## 6. 決めたこと

- 方式の**形**(Stage 3)は後回し。**名前と種別**(Stage 1-3)で装備フィルタは成立する
- 与圧無しの上限は設定値(既定 10,000ft)。法規の細かい酸素規定は当面持ち込まない
- ヘリ専用IFR経路は AIP に無い(ENR 3.4 Nil)ので、固定翼と同じ航空路を使う
- 既存の作法を守る: 生成物は `tools/gen_*.py` → `*.json`、UIは `.mtGrp` のグループ、
  版は `sw.js VER / VER_TAG / BUILD` を3つ一緒に上げる(CLAUDE.md 参照)

## 7. 未確認・要判断

- [ ] IAC のミニマ(DA/MDA/RVR)が本文レイヤから取れるか(Stage 1-4)
- [ ] ENR 3.1/3.3 の表で、1ページをまたぐルートの続き("(Cont'd)")の扱い
- [ ] 代替飛行場の最低気象条件のルール(国の標準値をどう持つか)
- [ ] IFRモードのUI: 既存のログ画面に組み込むか、別画面か

## 8. 再開のしかた

1. `IFR.md`(この文書)の Stage 1-1 から。まず `tools/gen_fix.py` を書く
2. 材料: `enr.txt` は scratchpad に無ければ
   `pdftotext -layout "~/Downloads/AIP File Download Service/1_AIP (PDF)/20260709/ENR_20260709.pdf" enr.txt`
3. 行番号の当たりは「2. データの棚卸し」の表
4. できたら BACKLOG.md の IFR の項を更新し、この文書の「7. 未確認」を潰していく
