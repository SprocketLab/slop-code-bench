# Word Stats - Checkpoint 2

## Overview
Extend the word counter to also count lines and filter stopwords.

## Requirements

### Input
The program reads text from stdin and accepts optional flags:
- `--lines`: Also output line count
- `--filter-stopwords PATH`: Filter out stopwords from the given file

### Output
- Default: Print word count
- With `--lines`: Print "words: N, lines: M"
- With `--filter-stopwords`: Exclude stopwords from word count

### Examples
```
$ echo "hello world" | python main.py
2

$ echo -e "hello world\nfoo bar" | python main.py --lines
words: 4, lines: 2

$ echo "the quick brown fox" | python main.py --filter-stopwords stopwords.txt
3
```

## Notes
- Stopwords file contains one word per line
- Stopword matching is case-insensitive
- All checkpoint 1 functionality must still work
