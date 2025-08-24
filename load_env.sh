#!/bin/bash

# config.env ファイルから環境変数を読み込む
export $(grep -v '^#' config.env | xargs)
