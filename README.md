# MihoWatanabeCalendar
<iframe src="https://calendar.google.com/calendar/embed?&showTitle=0&mode=AGENDA&src=2de570f4c3d8953da730014e5f8bd23d94a5cd77578363ab97590d810991b39d%40group.calendar.google.com&ctz=Asia%2FTokyo" style="border: 0" width="100%" height="300" frameborder="0" scrolling="no"></iframe>


渡邉美穂さんのスケジュールをGoogleカレンダーへ自動追加し、充実した推し活ライフをサポートします。  
[こちら](https://github.com/CircleTenThanks/Hinatazaka46Calendar.git)をベースに作っています。

## Googleカレンダー共有リンク

* Googleカレンダー
  * ご自身のGoogleカレンダーへ追加するには、上記カレンダー右下の `+Googleカレンダー`から設定してください。
  * スマートフォンでうまく設定できない場合は [#1](https://github.com/CircleTenThanks/Hinatazaka46Calendar/issues/1#issuecomment-1783007351) を参考にしてください。(`日向坂46`は`渡邉美穂`に読み替えてください)
* iCal形式(ICS形式)
  * [こちら](https://calendar.google.com/calendar/ical/2de570f4c3d8953da730014e5f8bd23d94a5cd77578363ab97590d810991b39d%40group.calendar.google.com/public/basic.ics)のリンクをコピーすると、iCal形式の共有リンクがコピーできます。お使いのカレンダーアプリがiCal形式に対応していれば、Googleカレンダー以外のカレンダーアプリへ追加することも可能です。
  * [iPhoneにインストールされているカレンダーアプリでの設定例](https://support.apple.com/ja-jp/guide/iphone/iph3d1110d4/ios)

## 仕組み

本リポジトリはRender.com の CRON JOB としてデプロイしており、上記Googleカレンダーへ自動的に登録されるようになっています。

渡邉美穂さんHPのWebサーバへの負荷を最小限にするためにも、上記のGoogleカレンダーが稼働している限りは、個別に本リポジトリをデプロイさせないでください。

なお、渡邉美穂さんHPの仕様変更等に伴って動作しなくなった場合のプルリクは大歓迎です。
