# SWIM AIP データ配信(AIXM)で見つかった誤り・欠け

> **2026-10-20 航空情報センター ヘルプデスクの回答**(10/16 送信の照会に対して)
> 1・2(下総・三沢の ILS の関連づけ): **11/26 発行分データ(11/12 配信予定)で修正**。→ 届いたら gen_ils_aixm の PDF 版の補いを外せるか確認
> 3(羽田の移設末端): annotation に平文で登録している。地図表示等の関係で物理的末端を登録している(仕様。直らない)
> 4(川口市付近 1,663ft の障害物): 情報元に照会中。次回発行時までに確認が取れなければ**いったん取り下げ予定**
> 5(民訓の連絡先): 要望は承知・実現を検討

HELI NAV のデータを AIXM と突き合わせたときに見つけた、**AIXM 側**の誤り・欠けの控え。
航空情報センター(SWIM)へ修正の要望を出すときの材料。アプリ側はそれぞれ回避済み。

- 対象ファイル: `AIXM_ALL_20261006150000.xml`(AIP データ配信サービス(初回)・2026-10-14 受信)
- 照合日: 2026-10-14

## 1. 下総 ILS RWY19 の関連づけが宇都宮の滑走路になっている
| 項目 | 値 |
|---|---|
| 地物 | Navaid `ILS-LOC 19`(designator **ISH**・109.1MHz・uuid `c3ed293c-04b7-4f52-bd0c-458eb4985050`)<br>Navaid `ILS-GP 19`(uuid `4a040e6f-bcca-45aa-b6f9-fd8ded1be506`) |
| servedAirport | RJTL(下総)… 正しい |
| runwayDirection | `214c4525-04e7-4232-803c-bc46e17703b5` = **RJTU(宇都宮)RWY 19** … 誤り |
| 正しいと思われる値 | `cbbd7419-7af8-4f88-9022-39916ca48d49` = RJTL RWY 19 |
| 根拠 | AIP RJTL AD 2.19(ILS-LOC 19 ISH 109.1MHz / ILS-GP 19)。宇都宮 RWY19 の THR から LOC まで約80km |

## 2. 三沢 ILS RWY28 の関連づけが新田原の滑走路になっている
| 項目 | 値 |
|---|---|
| 地物 | Navaid `ILS-LOC 28`(designator **IMIS**・uuid `0f10a09f-6507-4c40-916a-a30dd09817a6`)<br>Navaid `ILS-GP 28`(uuid `c7605a78-41b7-4949-8e41-2d030a33a94b`) |
| servedAirport | RJSM(三沢)… 正しい |
| runwayDirection | `813646d8-3148-47aa-b9d2-1bcc57513697` = **RJFN(新田原)RWY 28** … 誤り |
| 備考 | 新田原自身の ILS(`ILS-LOC 28` INH・`ILS-GP 28`)も同じ runwayDirection を指していて、1つの滑走路に2組の ILS が付いた形になっている |
| 根拠 | AIP RJSM AD 2.19(ILS-LOC 28 / ILS-GP 28) |

## 3.(参考)羽田の移設末端(DISTHR)が無い
| 項目 | 値 |
|---|---|
| 対象 | RJTT RWY 16L / 16R / 34R |
| 内容 | RunwayCentrelinePoint は role=THR(物理の末端)だけ。AD 2.19 の備考では GP は **Displaced THR** 基準(例「GP: 312m inside FM RWY16L Displaced THR」) |
| 影響 | 物理の THR を GP の基準にすると 400〜500m(GP 上で約70ft)ずれる。アプリは GP アンテナの位置から逆算して回避 |

## 4.(要確認)埼玉県南部の高さ 1,663ft の障害物
| 項目 | 値 |
|---|---|
| 地物 | VerticalStructure name **11000558** と **11000567**(同じ位置・同じ値で2件) |
| 位置 | 35.81156N 139.74481E(川口市付近) |
| 値 | type OTHER・高さ 1,663ft(507m)・標高 1,670ft・灯火あり・AREA1 |
| 備考 | AIS の障害物データ(AREA1 KML)にも同じ値で2件ある。地上 507m はスカイツリー(634m)に次ぐ高さで、該当する構造物が思い当たらない。単位(ft/m)の取り違えなどを疑う |

## 誤りではないが気づいたこと
- AREA1 の障害物に**同じ位置・同じ値の重複が 273件**ある(赤坂の同じ点に TOWER×3・BUILDING×1 など)
- 民間訓練試験空域・その他の空域に**連絡先(Controlling/Communication Facility)が無い**(空域を参照する AirTrafficControlService も無い)。
  ENR 5.3.1 の表にはある。HK3・TH11・CK3・CK4・CK12・CS1・CS3・KS13-1〜3・KS15・SM2 は前の版からも引けなかった
- 航空路の端点の navaid が **DesignatedPoint**(designator=MYE など navaid の識別符号)として載っている区間がある(Navaid を直接参照していない)

## 要望の文案
**2026-10-16 送信済み**(原口さん・Cc cab-swim-aisc。要点を先に5行・詳細を注釈にした形。障害物の重複の項は削って送った)

> 航空局 航空情報センター 御中
>
> AIP データ配信サービスで受信した AIXM データ(AIXM_ALL_20261006150000)を確認したところ、
> 以下の関連づけに誤りがあるように見受けられましたので、ご確認をお願いいたします。
>
> 1. 下総(RJTL)ILS RWY19(ILS-LOC 19 ISH・ILS-GP 19)の runwayDirection が、宇都宮(RJTU)RWY19 を参照しています。
> 2. 三沢(RJSM)ILS RWY28(ILS-LOC 28 IMIS・ILS-GP 28)の runwayDirection が、新田原(RJFN)RWY28 を参照しています。
> 3.(参考)羽田 RWY16L/16R/34R は GP が移設末端基準ですが、RunwayCentrelinePoint に DISTHR がありません。
> 4.(要確認)障害物 11000558・11000567(35.81156N 139.74481E)の高さ 1,663ft は、単位の取り違え等の可能性はないでしょうか。
>
> 各地物の uuid は別添のとおりです。
