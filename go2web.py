# go2web - A command-line HTTP client built on raw TCP sockets.
# No built-in/third-party HTTP libraries used — only raw sockets.

import sys

# CLI

HELP_TEXT = """\
Usage: go2web [option]

Options:
  -u <URL>           Make an HTTP request to the specified URL and print the response
  -s <search-term>   Search the term using DuckDuckGo and print top 10 results
  -h                 Show this help message

Examples:
  go2web -u https://example.com
  go2web -s "python programming"
  go2web -h
"""


def main():
    args = sys.argv[1:]

    if not args or "-h" in args:
        print(HELP_TEXT)
        return

    if "-u" in args:
        idx = args.index("-u")
        if idx + 1 >= len(args):
            print("Error: -u requires a URL argument.")
            sys.exit(1)
        url = args[idx + 1]
        print(f"TODO: fetch {url}")

    elif "-s" in args:
        idx = args.index("-s")
        if idx + 1 >= len(args):
            print("Error: -s requires a search term.")
            sys.exit(1)
        term = " ".join(args[idx + 1:])
        print(f"TODO: search for '{term}'")

    else:
        print("Error: Unknown option. Use -h for help.")
        sys.exit(1)


if __name__ == "__main__":
    main()
