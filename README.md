# MihoWatanabeCalendar

渡邉美穂さんのスケジュールをGoogleカレンダーへ登録するためのアプリケーションです。  
[こちら](https://github.com/ArgkGit/Hinatazaka46Calendar)をベースに作っています。

## Googleカレンダー共有リンク

* ご自身のGoogleアカウントに追加したい方は [こちら](https://calendar.google.com/calendar/u/0?cid=NTdmMmYyYTc2NmEzNmExOWZhZjQ3ODcwNzExNTA5OTE0ZGM4N2YzNzRmYjAzYzM4MTQwZTIyZTA2ZjdlZDFjNEBncm91cC5jYWxlbmRhci5nb29nbGUuY29t) 
    * うまく行かない場合は [#1](https://github.com/CircleTenThanks/Hinatazaka46Calendar/issues/1) へ
* ブラウザ上でGoogleカレンダーを見たい方は[こちら](https://calendar.google.com/calendar/embed?src=57f2f2a766a36a19faf47870711509914dc87f374fb03c38140e22e06f7ed1c4%40group.calendar.google.com&ctz=Asia%2FTokyo)

## 仕組み

本リポジトリはRender.com の CRON JOB としてデプロイしており、上記Googleカレンダーへ自動的に登録されるようになっています。

渡邉美穂さんHPのWebサーバへの負荷を最小限にするためにも、上記のGoogleカレンダーが稼働している限りは、個別に本リポジトリをデプロイさせないでください。

なお、渡邉美穂さんHPの仕様変更等に伴って動作しなくなった場合のプルリクは大歓迎です。
