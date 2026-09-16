# IFRモード 設計メモ(2026-09-13 起草)

**この文書は、どのセッション・どのモデルからでも作業を再開できるように書いてある。**
**Stage 1 は完了(2026-09-13, v6-141)**。次は「4. 進め方」の Stage 2 から。判断済みの事項は「6. 決めたこと」にある。

## 0. 現在地(2026-09-13)

| 段階 | 状態 | 成果物 |
|---|---|---|
| Stage 1-1 FIX | ✅ | `tools/gen_fix.py` → `fix.json`(**2,926点**・254KB) |
| Stage 1-2 航空路 | ✅ | `tools/gen_awy.py` → `awy.json`(**623本**=ENR 3.1 71本+ENR 3.3 296本+**ENR 3.5.1 直行経路 269本**・390KB) |
| Stage 1-3 方式索引 | ✅ | `tools/gen_proc.py` → `proc.json`(**113空港 SID 418/STAR 193/IAC 665**・77KB。索引の grep 数と完全一致) |
| Stage 1-4 IACミニマ | ✅ **取れた**(v6-156)。数字の文字化けは差し替えで戻る。表は原文のまま `iacmin.json`(548図) | `gen_proc.py` → `iacmin.json` |
| Stage 1-5 地図レイヤー | ✅ | 地物グループに **FIX** と **航空路** ボタン(`btnFix`/`btnAwy`。index.html の「FIXレイヤー」「航空路レイヤー」のブロック) |
| Stage 3 | 🔶 立川のみ(v6-152) | `SID_DEF` に図の文章を写す方式。空港を足すときは `sidTrackOf` のコメント参照 |
| Stage 2 | ✅ 第1版(v6-143) | **別画面**(タブ列の `IFR` ボタン → `#ifrModal`)。機体プロファイル(`hnav.acft`)・出発/目的/代替・経由FIX・経路探索(Dijkstra)・巡航高度・方式候補・METAR突合・燃料・「地図に反映」まで動く。残りは下の「Stage 2 の未了」 |

### Stage 2 の未了(次にやること)
- [x] **風**: レグごとに入力(共通の風+「＝前」で継ぐ)。WCA/MH/CH/GS/ETE を表に出す(v6-150)
- [x] **RCA** = SID終点までにAssigned ALTへ到達する点(v6-151)。SID実距離は図の値を手入力。「地図に反映」で飛行ログの注記点(括弧の内数)になり印刷にも載る。TOD(降下開始点)は未実装
- [x] **Stage 3(SIDの形)**: 立川 EDARR ONE / OMIYA ONE を `SID_DEF` に(v6-152)。RCA は折れ線上、SID線を地図に、経路長を飛行ログへ。次は館山・横田など使う空港から
- [x] 最低気象条件の目安の表は廃止。離陸ミニマは AD 2.22 原文(`tomin.json`)、進入ミニマは図参照(v6-152)
- [x] ILS CAT I/II/III を装備に(v6-152)
- [x] **TAF の表示**(v6-176): 中継 `relay/api/wx.js` でその場取得し、IFR 画面の気象欄に出発・目的・代替の TAF を表示
- [ ] **TAF** とミニマの突合(有効時間帯を ETA で切り出して、TEMPO/BECMG を含めて最悪値を比べる)
- [x] SID/STAR の**終点/始点のFIX**に経路を繋ぐ → 方式名がFIX名のものは繋いだ(v6-148)。名前が地名等のもの(18空港)は最寄りFIXへ仮の直行線のまま
- [x] 方式ごとの**実ミニマ** → 図の表を原文で表示(v6-156)。数値化はしない
- [ ] 代替飛行場の最低気象条件の**法規の値**(今は編集可能な既定値 600/3200・800/3200)
- [ ] 経路の**手直しUI**(今は経由FIXの指定と、地図に落としてからの既存の編集)
- [ ] 与圧なしで上限内の経路が無いときの案内(今は上限を外して赤で警告)

パーサの落とし穴は各 `tools/gen_*.py` の docstring と CLAUDE.md §8「IFRデータ」に書いた。
**AIRAC更新時は3本とも走らせ直す**だけでよい(手修正の箇所は無い)。

## 1. やりたいこと(要望の原文に沿って)

1. 機体プロファイルを設定: 搭載無線機、航法装置(VOR/DME/ILS/GNSS…)、燃料、与圧の有無
2. 出発・目的・代替飛行場を選ぶ
3. 装備から**使える出発方式(SID)・進入方式(IAP)・経路・高度・最低気象条件**を自動で見繕い、
   ログを作ってルートを引く
4. そのあと **FIX / SID / STAR / 進入方式を手で差し替え**られる(微修正)

要望にあった動画プレイリスト(YouTube)は**Claudeからは見られない**。出発方式・着陸方式の
根拠はすべてAIP(AD 2.22 / AD 2.24 / ENR 3 / ENR 4.3)から取る。

## 2. データの棚卸し(2026-09-13 に実測。AIRAC 20260709 → 2026-09-14 に 20260903 へ更新済み)

置き場: `~/Downloads/AIP File Download Service/1_AIP (PDF)/20260709/`
`enr.txt` は `pdftotext -layout ENR_20260709.pdf` の出力(4.5MB)。行番号はその中の位置。

| 出典 | 中身 | 量 | 取りやすさ |
|---|---|---|---|
| **ENR 4.3** (39651行〜51404行) | 重要地点=FIX の名前と座標。▲=義務位置通報点 △=任意 | **約1,900点** | ◎ 表。ただし**名前と座標が別の行**に割れる(ACAの座標表と同じ癖) |
| **ENR 4.1** | VOR/DME/TACAN/NDB | 129 | ◎ **既に取得済み** (`tools/gen_navaids.py` → `navaids.gen.js`) |
| **ENR 3.1** (10362行〜13957行) | 下層ATSルート(A/B/G/R/V/W) FIX列・磁方位・距離・MEA・高度方向 | **70本** | ○ 表。列が縦に散るので状態機械で読む |
| **ENR 3.3** (13968行〜31361行) | RNAV経路(Y/Z) 同上+航法仕様(RNAV5等)・MOCA・DME要件 | **261本** | ○ 同上。**主力の経路はほぼこちら** |
| **ENR 3.4** | ヘリコプター経路 | **Nil** | — AIPにヘリ専用IFR経路は無い |
| **ENR 3.5.1** (31376行〜33297行) | **直行経路**(navaid/FIX間の公示直行区間。磁方位・距離・MEA。DMEフィックス経由あり) | **269本**(両端から2回載るので行は353) | ○ 座標が無い。navaid(ENR 4.1+各AD 2.19)とFIXから引く。**v6-142で追加**(当初漏れていた) |
| **AD 2.24 索引** (各飛行場PDFの "CHARTS RELATED TO AN AERODROME" ページ) | SID/STAR/IAC の**名前と種別の一覧** | 113空港 / **SID 418・STAR 193・IAC 665** | ◎ 本文レイヤの1行1図。`grep "Standard Departure Chart\|Standard Arrival Chart\|Instrument Approach Chart"` で取れる |
| **AD 2.19** | 飛行場の航法援助施設(ENR 4.1 に無い 123局) | 各空港 | ◎ `tools/gen_adnav.py` → `adnav.json`。FIXの評定に出る navaid はこれで全部そろう |
| **AD 2.22** | 飛行方式(文章)。離陸最低気象条件など | 各空港 | △ 英文の散文。必要な数字だけ正規表現 |
| **AD 2.24 各図**(SID/STAR/IAC本体) | 経路の**形**、DA/MDA、RVR、MAP | 1,276枚 | ✕ **図。福岡TCAと同じ図の読み取り仕事**。全国は現実的でない |

⚠ IACのミニマ欄(DA/RVR)は本文レイヤから**取れない**(確認済み 2026-09-13: RJTT AD2-259 の
IACを `pdftotext -layout` に出すと数字が文字化け混じりで、表として読めない)。
ミニマは Stage 2 で「進入の種類ごとの標準値」を持ち、実値はチャートで確認する運用にする。

実測(パース後): FIX **2,926点**(ENR 4.3。上の「約1,900」は見積り違い。navaid名の義務通報点や
東経160°超の福岡FIR東端の点も含む)/ 航空路 **71+296本**(ENR 3.3 は "(Cont'd)" と
"Y10  Procedure for…" のような行末の注記を含めると 296 本になる。261 は注記なしの行数)。

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

## 5. データモデル(Stage 1 で確定した実物)

```
fix.json  { eff:"20260903", src, f:[ {n:"ABASA", lat, lng,
              c:1(▲義務)|0(△任意)  … 無ければ記号なし,
              id:"WKE"             … navaid名の点だけ(略号欄のID),
              rt:["N884","Y531"]   … ATSルート列(無い点もある),
              brg:"101°/14.0NM YNE, 277°/53.9NM IGE", ja:"アバサ" } ] }
awy.json  { eff, src, f:[ {n:"Y10"|"WKE-MVE"(直行経路は端点のID/FIX名), k:"LOW"(ENR 3.1)|"RNAV"(ENR 3.3)|"DCT"(ENR 3.5.1),
              spec:"RNAV5", sens:["VOR/DME","DME/DME","INS/IRS","GNSS"]   … RNAVだけ,
              pts:[ {n:"LUMIN", lat, lng, id?:"WKE"} … ]   … 直行経路の "TBE 10DME" は経路直線上に作った点,
              segs:[ {a:"LUMIN", b:"WAKKANAI", mag:194, true:183.8, dist:20.6,
                      up:"UNL", mea:"FL200"|7000, moca:3000|"FL150",
                      odd:"↑", even:"↓"      … その方向に飛ぶときの奇数/偶数高度(矢印は表の向き),
                      rmk:"DME required…", inh:["mea","mag"] … 前の区間から継いだ属性(3.1のみ) } ] } ] }
proc.json { eff, src, f:[ {icao:"RJTT", k:"SID"|"STAR"|"IAC", n:"VAMOS-RNAV", iaf:["TOHNE"](IACのみ・図にラベルがあるもの),
              rnav:1, typ:"ILS"|"LOC"|"LDA"|"VOR"|"VOR/DME"|"TACAN"|"NDB"|"RNP"|"RNAV"|"RNAV(GPS)"|"GLS"|"HI-ILS"|…,
              rwy:"34L", cat:"II/III", heli:1,
              nn:1  … 索引に名前が無い(自衛隊系。n は "#1" のような枚数。図参照) } ] }
hnav.acft { gnss, rnav(FMS等のRNAV装置・DME/DME/INS), vor, dme, ils, ndb, tacan, press,
            maxAlt:10000, vhf, uhf, roc(上昇率ft/min), vcl(上昇TAS kt), dev(自差表 12値) }
hnav.ifrWind { d, s }   … 共通の風(前回値)   … 燃料・TASは飛行ログ側の値を使う
```

グラフ化の勘所(Stage 2-3): `awy.json` の `pts` の名前は `fix.json` の `n` と一致する
(navaid名の点は `id` でも引ける)。同名で座標が僅かに違う点は同一点とみなしてよい。

## 6. 決めたこと

- 方式の**形**(Stage 3)は後回し。**名前と種別**(Stage 1-3)で装備フィルタは成立する
- 与圧無しの上限は設定値(既定 10,000ft)。法規の細かい酸素規定は当面持ち込まない
- ヘリ専用IFR経路は AIP に無い(ENR 3.4 Nil)ので、固定翼と同じ航空路を使う
- 既存の作法を守る: 生成物は `tools/gen_*.py` → `*.json`、UIは `.mtGrp` のグループ、
  版は `sw.js VER / VER_TAG / BUILD` を3つ一緒に上げる(CLAUDE.md 参照)

## 7. 未確認・要判断

- [x] IAC のミニマ(DA/MDA/RVR)→ 当初「取れない」としたが**取れた**(2026-09-14)。原文の表を選んだ進入方式ごとに表示
- [x] "(Cont'd)" → 同じ経路名に合流させる(`routes.setdefault`)。点の重複は名前で除く
- [ ] 代替飛行場の最低気象条件のルール(国の標準値をどう持つか)
- [x] IFRモードのUI → **別画面**(ユーザー指示 2026-09-13)
- [ ] ENR 3.1 の先頭区間に MEA が無いものがある(V13 CHITOSE-SIRAO など 478区間中77)。
      表で MEA が最初の区間より後にしか書かれていないのか、取りこぼしかは未確認
- [ ] `proc.json` の `nn`(名前の無い方式・20件)は装備フィルタに掛けられない。図参照と出す

## 8. 再開のしかた

1. **「0. 現在地」の Stage 2 の未了から**。コードは index.html の
   `/* ───────── IFR計画(別画面・IFR.md Stage 2) ─────────` のブロック(`openIfr` / `ifrGraph` /
   `dijkstra` / `cruiseAlt` / `procOk` / `wxJudge` / `renderIfrOut`)。落とし穴は CLAUDE.md §8「IFRデータ」の末尾
2. データは `fix.json` / `awy.json` / `proc.json`(いずれも `fetch('xxx.json?v='+VER_TAG)`)。
   地図側の読込関数 `loadFix()` / `loadAwy()` をそのまま使える
3. 生成器を直すときの材料: `enr.txt` は scratchpad に無ければ
   `pdftotext -layout "~/Downloads/AIP File Download Service/1_AIP (PDF)/20260709/ENR_20260709.pdf" enr.txt`
   行番号の当たりは「2. データの棚卸し」の表
4. できたら BACKLOG.md の IFR の項を更新し、この文書の「7. 未確認」を潰していく
