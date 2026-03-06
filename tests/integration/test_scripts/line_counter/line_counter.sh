#!/bin/bash

count_lines() {
    input_text="$1"
    line_count=$(echo "$input_text" | wc -l)
    echo "Line Count: $line_count"
}

if [ "$#" -ne 1 ]; then
    echo "Usage: ./line_counter.sh '<input_text>'"
    exit 1
fi

input_text="$1"
count_lines "$input_text"
