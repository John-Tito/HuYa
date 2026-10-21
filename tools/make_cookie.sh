#!/usr/bin/bash

script_dir=$(cd "$(dirname "$0")" && pwd)

cookie_1=$(cat $script_dir/../.huya_cookie/cookie_1.txt )
cookie_2=$(cat $script_dir/../.huya_cookie/cookie_2.txt )

cookies="$cookie_1\n$cookie_2"

echo "HUYA_ROOMS=\"998\"" > $script_dir/.env
echo "HUYA_SEND_DRY_RUN=\"1\"" >> $script_dir/.env
echo "HUYA_COOKIES=\"$cookies\"" >> $script_dir/.env
echo "CHROME_BINARY=\"/home/john/.cache/selenium/chrome/linux64/153.0.8010.36/chrome\"" >> $script_dir/.env