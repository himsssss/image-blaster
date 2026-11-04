#!/bin/sh
# usage: fetch_view.sh <forge_dir> <object> <view> <result_url>
mkdir -p "$1/objects/$2/views" && curl -sf -o "$1/objects/$2/views/$2-$3.png" "$4" && echo "$2-$3 ok"
