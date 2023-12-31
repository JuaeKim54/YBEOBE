import sys

if len(sys.argv) < 2:
    print(
        f'[-] Only one commnad required which is in ("train", "inference", "interactive", "train_tokenizer)',
        file=sys.stderr,
    )
    exit(-1)

_, command, *arguments = sys.argv

if command == "train":
    from .train import main, parser
else:
    print(f'[-] Please type command in ("train")', file=sys.stderr)
    exit(-1)

exit(main(parser.parse_args(arguments)))
