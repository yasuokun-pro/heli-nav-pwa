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
| Stage 3 | 🔶 立川(v6-152)・入間(v6-196)・厚木(v6-197)・下総(v6-198)・木更津(v6-199)・館山(v6-200)・宇都宮(v6-201)・百里(v6-202)・横田(v6-203)。**立川から近い自衛隊飛行場はここまで**。次は使う空港から | `SID_DEF` に図の文章を写す方式。空港を足すときは `sidTrackOf` のコメント参照。**次は 百里**(立川から近い自衛隊飛行場の順) |
| Stage 2 | ✅ 第1版(v6-143) | **別画面**(タブ列の `IFR` ボタン → `#ifrModal`)。機体プロファイル(`hnav.acft`)・出発/目的/代替・経由FIX・経路探索(Dijkstra)・巡航高度・方式候補・METAR突合・燃料・「地図に反映」まで動く。残りは下の「Stage 2 の未了」 |

### Stage 2 の未了(次にやること)
- [x] **風**: レグごとに入力(共通の風+「＝前」で継ぐ)。WCA/MH/CH/GS/ETE を表に出す(v6-150)
- [x] **RCA** = SID終点までにAssigned ALTへ到達する点(v6-151)。SID実距離は図の値を手入力。「地図に反映」で飛行ログの注記点(括弧の内数)になり印刷にも載る。TOD(降下開始点)は未実装
- [x] **Stage 3(SIDの形)**: 立川 EDARR ONE / OMIYA ONE を `SID_DEF` に(v6-152)。RCA は折れ線上、SID線を地図に、経路長を飛行ログへ。次は館山・横田など使う空港から
- [x] **入間 5本**(SUPAX/HATAR/IRUMA REVERSAL/BUSYU/HATSU ONE・v6-196)。`then`(SID 終点のあとの区間・旋回の向き指定)と
  `grad`(図の Note の要求上昇勾配 → 必要な上昇率を表示、装備の上昇率が足りなければ赤)を追加。
  ⚠ 入間の索引は**1枚の図に複数の SID**("SUPAX, HATAR")。ルートの最初の FIX で SID を選ぶ(`sidTrackOf` の `endFix`)。
  ⚠ 自衛隊飛行場の AD 2.12 は真方位が "To be issued" のことが多い → 滑走路は OSM の aeroway=runway から(Overpass は maps.mail.ru のミラーが通る)
- [x] **厚木 2本**(YOKOTA TWO / ZUSHI ONE・v6-197)。手順に `{dme:n}`(その針路で DME まで)・`{intercept:ラジアル}`・
  `{to:'名前'|{rad,dme}, turn}`(点へ。旋回の向き指定可)を足し、滑走路ごとに全く違う経路を書けるようにした。
  ⚠ 図の文からの自動抽出(proc.json の to)は、同じページの別の文の局まで拾う(YOK を足そうと gen_proc を広げたら
  成田 AKAGI→TTE・百里 GOPVU→MXT と壊れたので戻した)。**SID_DEF がある飛行場は `procEnd` でその終点を正とする**
- [x] **下総 4本**(KOGAR TWO / UTSUNOMIYA ONE / TSUGA FOUR / WEST FIVE・v6-198)。`{arc:'L'|'R',dme,to}`(DME アーク)と
  滑走路ごとの要求上昇勾配 `grad:{'01':{pct,to},'19':{…}}` を追加。
  ⚠ Overpass が全ミラーで落ちていたときは OSM 本体の API(`api.openstreetmap.org/api/0.6/map?bbox=`)で滑走路を取れた
- [x] **木更津 2本**(KOSKA ONE / TSUGA TWO・v6-199)。KOSKA は RWY20 が "(Not established)"。
  設定の無い滑走路を選んだときは、ある方の滑走路で描いて「RWY20 はこの SID が設定されていない」と出す(`rwyNote`)。
  ⚠ 経路探索は滑走路を見ないので、RWY20 でも KOSKA を選ぶことがある(画面の注意書きで分かるようにしてある)
- [x] **館山 1本**(TATEYAMA REVERSAL THREE・v6-200)。滑走路 300m、AD 2.12 に THR 座標あり(真方位は計算)。
  終点が飛行場自身の TET(8NM 以内)。v6-201 から経路網でも TET に繋ぐ(下記)
- [x] **宇都宮 3本**(KOGAR FIVE / MIKRA FOUR / UTSUNOMIYA REVERSAL ONE・v6-201)。SID-3 は文字コードのずれたフォント(gen_proc.dec で読む)。
  - `climbTo` の高度は**経路の長さから**出す(離陸端の標高+経路長を上昇速度・上昇率で上った分)。"via R030 to 4000FT" のように
    途中の区間で高度を指定するものがあるため。先頭の climbTo は従来と同じ値になる
  - `procEnd`: SID_DEF の終点が全部 8NM 以内(反転 SID)なら、その局(TET/JDT)に繋ぐ。8NM で捨てていた頃は館山が
    最寄りの FIX へ仮の直線、宇都宮は図の文の抽出で REVERSAL が MIKRA に繋がっていた
  - SID の辺の長さを**形の経路長**にした(`sidLenMin`・滑走路のうち短い方)。直線だと反転 SID が 0.4NM で選ばれやすかった
- [x] **百里 5本**(GOPVU ONE / NAKAH FIVE / OGITU EAST・WEST ONE / HITAKA ONE RNAV1・v6-202)。平行滑走路4本。
  RNAV は図の表(Path/Waypoint・真コース・VAR 7.8°W・H1R00 の座標)から。
  同じ終点の SID が図に複数(OGITU E/W)あれば、その滑走路で短い方を選ぶ。
  ⚠ 百里の SID は全部北〜北東へ出るので、西へ向かう計画も NAKAH から HUC へ戻る経路になる(公示どおり)
- [x] **横田 5本**(BUSYU TWO / BREEE SIX / TIMAP FIVE / KANTO ONE・FUSSA TWO(RNAV1-GPS)・v6-203)。図は DoD FLIP の転載で
  **文字の層が無い画像** → `pdftoppm -r 110` で描いて目で読んだ。BREEE・TIMAP は ENR 4.4 に無く、図の DME から R178/18・R003/18 で置いた。
  "Climbing turn" は TERPS どおり 400ft AGL で旋回開始。BUSYU の要求上昇率の表(60kt で 360/383fpm)を勾配 5.9%/6.3% に直した。
  - SID の終点が経路の最初の点と違う(経路網に無い終点の SID を手で選んだ)ときは `off` を立て、形は出すが距離・RCA には使わない
  ⚠ 横田は BREEE・TIMAP が航空路に繋がっていないので、計画では BUSYU からしか出られない(東・南へも一度西へ出る)
- [x] **SID のチップで選び直すと経路ごと組み直す**(v6-204・`ifrForceSid` → `ifrRunPlan(true)`)。出発飛行場をその方式だけで
  経路網に繋いで探し直すので、「地図に反映」でその SID の線と経路がそろう。「計画を作る」を押し直すと自動に戻る。
  その SID の終点から先が繋がらない(横田 TIMAP など)ときは警告を出して自動に戻す。
  ⚠ v6-196〜203 は SID のチップを押すと `P.G`(renderIfrOut の引数に G は無い)で例外になり、反応しなかった。
    選択だけ残っていて、次に進入方式を押した時の描き直しで SID が変わって見えた(ユーザー指摘)
- [x] **会合針路で前方に交わらないときの近似を変えた**(v6-205・ユーザー指摘「宇都宮 REVERSAL の線が変」)。
  図の旋回は固定翼の大きな半径で描かれていて、80kt の標準旋回だと旋回後の位置が局に近すぎ、公示の針路ではラジアルに交わらない。
  以前は針路だけラジアルに合わせて**横にずれたまま平行に**飛んでいた(REVERSAL RWY19 は R030 の東 1NM 以上)。
  今は**ラジアル上の少し先の点(局から max(2, 今の距離+1)NM)へ直進して乗る**。画面に「近似」と出す(`approx`)。
  61本中11本が該当(下総 RWY19 の2本・宇都宮2本・百里 RWY21 の7本)、長さの差は 0.4NM 以内
- [x] 最低気象条件の目安の表は廃止。離陸ミニマは AD 2.22 原文(`tomin.json`)、進入ミニマは図参照(v6-152)
- [x] ILS CAT I/II/III を装備に(v6-152)
- [x] **TAF の表示**(v6-176): 中継 `relay/api/wx.js` でその場取得し、IFR 画面の気象欄に出発・目的・代替の TAF を表示
- [x] **TOD(降下開始点)**(v6-234): 経路の最後の点(IAF・STAR の終点など飛行場の手前の点)に「IAF 高度」で着くように、
  巡航高度から装備欄の**降下率・降下速度**(空なら巡航 TAS)で後ろ向きに逆算する(`ifrTod`)。GS はレグごとの風込みで、
  複数のレグにまたがってよい。IAF 高度は**目的地+進入方式ごと**に `hnav.todAlt` に覚える(進入方式のチップを替えると読み直す)。
  表に「(TOD …)」行(レグの始めからの距離/時間・IAF までの降下距離/時間)、「地図に反映」で注記点 "(TOD 4,000ft 23.5NM)" になる。
  RCA と同じレグに入るときは距離の順に並べる。経路が短くて降り切れない・上昇を終える前に降下になるときは赤で出す
- [x] **進入図の IAF の読み取り修正・必要装備・進入方式の選び直し・進入方式の形**(v6-239〜241・ユーザー指摘「百里で HUC が IAF になっている」)
  - IAF: 上の行の行末の語を取っていた(百里 ILS Y の断面図の「TAIYO …… HUC」)。上の行から取るときは "(IAF)" と列が重なる語だけ(`iaf_names`)。全国 145 方式が変わった
  - 必要装備: 図の右上「EQPT REQUIRED」(DME / DME・VOR / TACAN / –)を proc.json の `eq` に。`procOk` で装備と照合(DME は TACAN でも可)。308/663 方式で取れた
  - 進入方式のチップを押すと**その方式の IAF へ向かう経路に組み直す**(`ifrForceIac`・SID と同じ)。飛行ログは「地図に反映」をもう一度
  - **進入方式の形 `IAC_DEF`**(まず百里 15 方式。ILS Z/LOC Z は IF からでレーダー誘導前提なので書かない): IAF→放射線・DME アーク→最終進入→滑走路(周回は MAPt)。
    IAF→飛行場の辺の長さをこの経路長にする(以前は直線で、飛行場の真上の点が「ただ」に見えた)。「地図に反映」で最後の区間の距離を上書きし、橙の破線で描く。
    百里: ILS X 57.2NM・ILS Y 51.4NM・VOR RWY03R 60.0・TACAN RWY21L 34.4・RNP RWY21R 16.2 など
  - 形のある飛行場では **STAR の終点→飛行場の直線の近道を作らない**(STAR のあとも進入を飛ぶのに直線だと必ず短く見えた)
  - 飛行場の navaid(装備で使えるもの)を**いつも**経路網に入れる。以前は IAF を繋ぐついでにしか入らず、百里の HUC が TACAN なしだと消えて宇都宮回りになった
  - 計画は自分の装備と公示の方式だけで立てる(レーダー誘導・GCA は前提にしない・ユーザー確認)
- [x] **TAF とミニマの突合**(v6-236・`tafParse`/`tafWorst`/`ifrTafChkHtml`): 出発(ETD)・目的(ETA)・代替(代替への ETA)の前後1時間で、
  TAF の**主の予報**(基本に FM・終わった BECMG を当てる。変化中の BECMG は前後の悪い方)と **TEMPO/PROB** を分けて一番悪い視程・雲高を出す。
  比べる値(雲高・視程)は**パイロットが AIP の表・代替の規則から読んで入れる**(表は数値に解釈しない方針のまま)。飛行場+方式ごとに `hnav.wxMin`。
  ✓ 主は上回る / ✗ 主で下回る / ⚠ TEMPO・PROB で下回る を出す。ETD は NOTAM タブの「出発」(`hnav.ntmEtd`)と共通。
  雲高 = BKN/OVC/VV の一番低い層、CAVOK・NSC・SKC は雲なし、書いていない要素は前の値を継ぐ。TAF の期間外・一部期間外も出す
- [x] SID/STAR の**終点/始点のFIX**に経路を繋ぐ → 方式名がFIX名のものは繋いだ(v6-148)。名前が地名等のもの(18空港)は最寄りFIXへ仮の直行線のまま
- [x] 方式ごとの**実ミニマ** → 図の表を原文で表示(v6-156)。数値化はしない
- [ ] 代替飛行場の最低気象条件の**法規の値**(今は編集可能な既定値 600/3200・800/3200)
- [x] 経路の**手直しUI**(v6-235): 経路の表の各行に **固定**(必ず通る=経由に入れる)・**✕**(通らない)・**＋**(この点のあとに経由点を足す)。
  押すとその場で組み直す(選び直した SID は保つ)。状態は入力欄「経由」「通らない(`hnav.ifr.avoid`)」そのもので、表の上に出し「手直しを全部外す」で戻す。
  「通らない」は `dijkstra` で `G.avoid` の点に入らない。navaid は経路網では名前(SEKIYADO)なので、略号(SYE)で入れたら名前に直して入力欄も書き換える。
  ⚠ ＋で足すときは、その手前の点も経由に固定する(しないと順番が保てない)。繋がらないときは「手直しを全部外す」を出す
- [x] **与圧なしで上限内の経路が無いときの案内**(v6-237・`planWith`/`ifrCapHtml`): 上限内で繋がらなければ、上限を**区間の MEA の値ごとに上げて**
  探し直し、最初に繋がった=**必要な高度が一番低い経路**を使う(以前は上限を外した最短経路で、FL240 の経路を選ぶことがあった)。
  巡航高度の欄に、上限を超える区間(区間名・MEA)・その経路の MEA 最大・上限を気にしなければ何 NM 短い経路があるか・対策
  (表の ✕/固定/＋ で手直し・与圧/酸素・VMC の確認)を出し、経路の表の MEA を赤くする。MEA は上限内でも奇偶の高度で超える場合はその旨。
  例: 羽田→富山 上限 6,000ft → Z119 の MEA 7,000ft の2区間(上限を外すと 168.8NM 短いが MEA FL240)

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


## v6-177 RNAV 区間を navaid のラジアルで通す / 方式の逆走を禁止
- **経緯**: 立川→宇都宮で OMIYA→SEKIYADO→TOHNE→LEMUM→KOGAR と遠回り(87.3NM)。
  OMIYA–KOGAR は **Y588(RNAV5)にしか無い**ので、RNAV 無しの機体では使えなかった。
- **ユーザー指摘**: OMIYA は JDT で標定できる。ENR 4.3 の OMIYA の評定は XAC・SHT・SYE・TNT の4つだけで
  JDT は載っていないが、**座標から計算すると JDT 209°/38.4NM、KOGAR(公示 JDT 209°/25.4NM)と同じラジアル上で横ずれ0.06NM**。
  つまり Y588 の OMIYA–KOGAR は JDT R-209 そのもので、TACAN があれば RNAV 無しで飛べる。
- **対応** `radialOnSeg()`: RNAV の航空路の区間でも、両端が同じ navaid の同じラジアル上(角度差1°・横ずれ0.5NM以内、
  navaid から3NM以上)で、**片端が公示の評定でその navaid を使っていれば**ラジアルの辺として通す。
  公示に無い側の評定はレグ表に「(計算)」付きで出す。公示の直行経路が同じ線にあればそちらを優先(0.5NM 不利)。
  → 立川→宇都宮 71.3NM、宇都宮→立川 54.1NM。
- **ついでに見つかった既存の不具合**: 代替=出発地(立川→宇都宮→立川 など)で、SID の辺を逆向きに使って着陸していた
  (辺を両向きに張っているため)。`dijkstra` で「SID で飛行場に入らない・STAR/IAF で飛行場から出ない」を追加。
- [ ] navaid の使用不能区域(ENR 4.1 Unusable。JDT は 150-160°/310-330°/350-360° の一部)を見ていない
- [x] ラジアル接続で navaid 種別(TACAN/VOR)と装備のチェックボックスを照合する → v6-242 `navRadOk()`

## v6-242 ラジアル接続を装備で絞る / 代替の最低気象条件の表がスマホで飛び出す
- **ユーザー判断 B(2026-10-18)**: 局の種類で見る。TACAN だけの局 = TACAN、VOR = VOR、**VORTAC はどちらでも可**
  (ENR 4.3 の評定が「HUC TACAN」と書いてあっても HUC は VORTAC なので VOR で同じ線を飛べる)。DME・LOC だけの局はラジアルなし。
  `navRadOk(id,ac)` を `navNode()`(評定の辺)と `radialOnSeg()`(RNAV 区間のラジアル)の両方で見る。`ifrGraph` が `G.ac` を持つ。
- 立川→百里(GNSS/RNAV なし)の結果: VOR だけ・TACAN だけ・両方とも OMIYA>SEKIYADO>TOHNE>LEMUM>HUC>NAKAH。
  TACAN だけだと ILS X は図の必要装備 VOR で外れて TACAN A(NAKAH から)になる。
- **KOGAR を通らない理由(質問への答え)**: OMIYA>KOGAR>HUC は実距離で 0.4NM 短い(136.2 対 136.6)が、OMIYA–KOGAR は Y588(RNAV)で、
  RNAV なしでは JDT R-209 のラジアル(`radialOnSeg`)扱い = **0.5NM の不利**を付けているので負ける。
  さらに JDT は TACAN だけの局なので、VOR だけの機体ではそもそも使えない(v6-242 から)。
- 横に動く件: `table.altMin` の td が全体の `td{white-space:nowrap}` を継いで 575px になり、シート全体が横に動いていた。
  altMin の td/th を折り返しに(375px 幅で 5 経路を測って横の飛び出しゼロ)。AIP のミニマの表は枠の中だけで横に動く(従来どおり)

## v6-243 航空路(従来型)の装備チェックを区間ごとの navaid で
- それまで: LOW は「VOR があれば可」、DCT は「VOR か TACAN があれば可」と経路の種類だけで見ていた。
- `awyNavBlock(r,a,b,ac)`: 区間を飛ぶのに使う navaid = **航空路の上で区間の手前側・先側それぞれ一番近い navaid**
  (GOT-GTC の MIKRA–GTC 15DME なら GOT(TACAN)と GTC(VORTAC))。どちらかが `navRadOk`(v6-242 の規則 B)で使えれば可。
  航空路の上に navaid が無い区間(KOGAR-LEMUM など)は両端 FIX の ENR 4.3 評定の navaid のどれか。それも無い(洋上)ときは従来どおり。
- 受けられない navaid の区間でも、使える navaid の同じラジアル上なら `radialOnSeg` で通す(RNAV 区間と同じ・0.5NM 不利)。
- TACAN は DME を含むので、DME が要る区間・DME フィックスは TACAN でも可(`segBlockRest`)。
- 結果(上限 10,000ft・GNSS/RNAV なし):
  - 宇都宮→新潟: VOR だけ・TACAN だけとも MIKRA>GTC 15DME>NIIGATA 106.6NM。両方なしは「経路が見つからない」
  - 立川→百里: 両方 136.6NM(TOHNE>LEMUM)/TACAN だけ 93.0NM(KOGAR、JDT R-209、TACAN A)/
    **VOR だけ 188.2NM(SEKIYADO>OKUJI>HUC)**。LEMUM–TOHNE(直行経路 LEMUM-SHT)は SHT R-346 = TACAN だけの局なので VOR では飛べない
- 宇都宮→新潟が「作れない」とのユーザー報告: プレビューでは上限 10,000ft で作れる(MIKRA–GTC 15DME の MEA 10,000ft)。
  上限 9,000ft なら福島回り 198NM、8,000ft なら仙台・山形回り 316NM(上限超えの警告つき)。実機の状態は未確認

## v6-244 航空路の距離の読み違い(ENR 3.1)で経路が不当に短く見えていた
- **ユーザー報告**: 宇都宮→新潟が KOGAR>…>SEKIYADO(SYE)>V15 になり MIKRA>GTC にならない(与圧あり等、上限 11,000ft 以上のとき)。
- 原因: awy.json の V15 NIIGATA–KALON が **15NM**(座標からは約 92NM)。V15 経由が合計 86NM に見えて MIKRA 経由 106.6NM に勝っていた。
  座標からの距離と 3NM かつ1割以上ずれる区間が **28 区間**(A582・R211・R217・V1・V2・V3・V4・V7・V13・V15・V30・V31・V33・V34・V36・V37・V52・V54・Y46)。
  `gen_awy.py` の `parse_31` が距離を桁 40〜52 の最初の数字で拾っていて、別の区間の数字を取っているらしい(未調査)。
- 対応(アプリ側の安全策): `ifrGraph` で公示距離が座標からの距離と 3NM かつ1割以上ずれたら座標の距離を使う。
  座標が重なっている区間(Y46 ALBAT–KISEI 0.0NM)は座標が誤りなので公示値のまま。地図の航空路ポップアップは公示値(読んだ値)のまま。
- 結果: 宇都宮→新潟は 与圧あり・上限 10,000ft・GNSS ありのどれでも MIKRA>GTC 15DME(106.6〜106.9NM)。
- [x] `gen_awy.py` の ENR 3.1 の距離の読み方を直して awy.json を作り直す → v6-245

## v6-245 gen_awy.py の ENR 3.1 の読み方を直す(距離・磁方位)
- 距離の読み違い28区間の原因は3つ:
  1. **座標の無い点**(「(GTC 15 DME)」「(KCC 75 DME)」「(MRE 32 DME)」)が途中に挟まり、前後の距離が2つ並ぶ → 最初の1つしか取っていなかった。**足す**
  2. 距離の列を桁 40〜52 で拾っていて、桁 48〜50 の **CHANGE-OVER POINT(COP)の距離**(「113 ---- 80」)を取っていた → 桁 38〜46 に
  3. 区間が**ページをまたぐ**と同じ距離が両方のページに載る(A1 KAGOSHIMA–KAZAN 31/31) → ページ替わりの直後の同じ値は足さない
- ついでに: 座標「1335006.20 E」(E の前に空白)で V28 KIBI が落ちていた(AIXM の組み直しで補われていた)→ COORD を空白許容に。
- 磁方位: 方位は**点の名前の行・座標の行**にも乗る(「314150.00N/1303458.59E   240」「△ KALON   ----」)のに区間の行だけ見ていた。
  始点の座標の行〜終点の座標の行(左28桁は除く)で探し、ページ替わりは越えない。
- AIXM(2026-10-01)との突き合わせ(ENR 3.1 の 478 区間): 距離の不一致 28 → **0**、磁方位が読めた区間 126 → 225(往)・142 → 218(復)、
  食い違い 往 6 → 2・復 2 → 3(G597 OGAKI–KCC 105/107 など 2〜3°。R220 NUBDA–NOGAL の復 330/052 は前から)。
- `--airac` を追加(指定が無いと一番新しい発行の PDF を取っていた)。手順: `gen_awy.py --airac 20261001` → `fix_awy_aixm.py --at 2026-10-01 --write`
- 結果: 立川→千歳(VOR+TACAN)が 花巻回り 448NM(V33/V34/V36 の短すぎる距離のせい)→ 472NM に。宇都宮→新潟は MIKRA>GTC 106.6NM のまま。
  v6-244 のアプリ側の安全策は残す(今は Y46 ALBAT–KISEI・KISEI–EMSUV だけ = 座標が重なっている別の誤り)

## v6-246 Y46 KISEI の座標(AIP の誤記)と ENR 3.3 の属性の行ずれ
- **Y46 KISEI**: ENR 3.3 の表そのものが KISEI の座標を1行上の ALBAT と同じ「332152N 1352629E」で刷っている(AIP の誤記)。
  ENR 4.4・V37・Y43・AIXM はどれも 332804N 1351944E。`gen_awy.py` の最後で、名前の点(navaid でない)が ENR 4.4(fix.json)と
  0.5NM 以上違えば fix.json の座標にして警告を出す(今は KISEI だけ。ZYT と FIX の CHITOSE は別物なので navaid は見ない)。
- 0.5NM 単位で全区間の距離を座標と比べ直して見つかった **Y51 DISSH–LANAT 124.15NM**(AIXM 113.0): 桁100から右の周波数欄
  「Freq:124.15(134.4)」を距離に取っていた。ENR 3.3-112 は区間の属性が座標の行の**1行上**に刷られていて座標の行に距離が無い。
  同じ理由で **Y512 ELDAK–NIIGATA** は属性が**1行下**(距離が無く、上限に備考の「(at or above FL335)」を取っていた)。
  → 座標の行の桁100までを見る。「距離 上限」が無ければ1行上、次に1行下の行を使う。
- [MOCA] を座標の行の下3行まで探す処理(先行ブランチで 20261029 用に入れたもの)を main にも入れた → 10/01 でも18区間の MOCA・真方位が埋まる。
- 結果: 距離の無い区間 0、座標からの距離と 1.5NM かつ5% 以上ずれる区間 0(全 2281 区間)

## v6-258 IFR ログ印刷(IFR 計画の画面から)
- ユーザー要望(2026-10-19): VFR のログ(地図の経路から作る)とは別に、IFR 計画の結果から IFR 用のログを作る。
  出発→目的と目的→代替を別のログにし、どちらも A5 1面に収まれば同じ紙(A4)の左右に。
- IFR 計画の結果の「🖨 IFR ログ印刷」→ `ifrPrintLog()`。データは `renderIfrOut` が `ifrPlanRes.prt`(rows/rowsA/P/必要燃料)に残す。
- 列: FIX | IDENT/FREQ | ROUTE/MEA | MAG CRS | WIND(°T/kt)/WCA | MH | GS | DIST/REMAIN | EET/REMAIN | ETA/ATA | FUEL/REMAIN
  - IDENT = 評定に使う navaid(装備で受けられる局を優先 `navRadOk`)+ ラジアル/DME(HUC R272 D27.6)、FREQ = VOR の周波数 / TACAN の CH(`navFreqTxt`)。
    navaid そのものの点はその局、飛行場は TWR 等の周波数
  - ETA は NOTAM タブの「出発」(ETD)を入れていれば ETD + 累計。空なら手書き
- NOTES: 出発・目的(代替)の飛行場の周波数/標高/滑走路、SID/STAR/IAC、巡航高度・Assigned・IAF 高度・TAS・FF、RCA・TOD、燃料(TRIP+ALTN+RES=必要 ｜ FOB)
- 印刷の共通部分を `prPrint(sections)` に切り出した(VFR も同じ)。面割り・縦横・iPhone 対策(v6-249〜256)は共通

## v6-261 関東の SID の形がある飛行場の進入方式の形(立川・入間・厚木・下総・木更津・館山・宇都宮・横田)
- ユーザー要望(2026-10-19): SID の形を作った飛行場の進入も。AIP AD2.24-IAC の図 21 枚から写した(百里と同じ書き方)。
  | 飛行場 | 方式(入口→…) |
  |---|---|
  | 立川 RJTC | TACAN RWY01(ANOBU→VALMO→MAPt)・TACAN A(OROGU→TAVAX→TNT) ※どちらも IF(待機あり)から |
  | 入間 RJTJ | TACAN 17(OGAWA)・35(KANAI)・HI-TACAN 17(JOSHU)・35(TOMEI→R172 20DME)→8DME→MAPt |
  | 厚木 RJTA | ILS Y(SYONA→D11 アーク→RUMED→PUKUK→THR01)・TACAN 01(SYONA→アーク→ADKET→ESDUS→MAPt D0.9) |
  | 下総 RJTL | ILS Y/Z(TOHNE→D17 アーク / ASEKI→BANDO→JOBAN→THR19)・TACAN 19(TOHNE→アーク→ASEKI→USIKU→SHT) |
  | 木更津 RJTK | TACAN 02(AMAHA→EGAWA→MAPt) |
  | 館山 RJTE | TACAN A(SAPIM→D11 アーク→OLSAS→UKAKU→TET→R340 D1.0) |
  | 宇都宮 RJTU | TACAN 01(IPNAX→D8.7 アーク→OBMAP→RINTU→MAPt) |
  | 横田 RJTY | HI-ILS Y 18/36(IMOTU→15DME アーク)・ILS Z 18(ULENI)/36(OKURA)・RNAV 18(BODAI)/36(WHILY・MESTR) |
- 仕組みの追加: ①入口が複数の方式は `{IAF:配列}`(下総 ILS)・`iacTrackOf(icao,name,iaf)`
  ②図に IAF が無く IF に待機がある方式(立川・木更津)は最初の点を入口に(`iacIafs`)。IF に待機の無い方式(厚木 ILS Z・百里 ILS Z)は
  レーダー誘導前提なので書かない ③ENR 4.4 に無い点(入間・横田)は `fix:{名前:[ラジアル,DME]}` → 読み込み時に FIX に足す(`iacFixInject`)
  ④横田の進入復行の待機点は `mah` に書く(FLIP の図から取れない)。⚠ 横田の RNAV の点は図に座標が無く、図の距離からの近似
- 直したもの: 代替の起点(進入復行の待機点)が「SYONA 00 VDP」のように崩れて取れず、さらに進入方式の形がある飛行場は IAF の辺しか無く
  飛行場から出られずに「代替までの経路が見つからない」(厚木→下総)。待機点は mahT の先頭の語も見る・待機点が無ければ飛行場の navaid へ
  出る辺(`出発(navaid)`・入る向きには使わない)を足す
- [ ] 横田は YOK から出る公示の経路が少なく、代替(TIMAP→YOK→HATAR→宇都宮回り)が大回りになる。navaid 間の直行(ラジアル)をどう扱うか

