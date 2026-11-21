"""Checks of built demo pages, each run from the repository root on a folder of pages or on one page:

  python -m demo.page_builder.checks.fit FOLDER_OR_PAGE     no word of the diagram cut, at 7 window sizes (22 with --more), in every view
  python -m demo.page_builder.checks.walk FOLDER_OR_PAGE    every moment of the replay, and the Data view's filters and parts
  python -m demo.page_builder.checks.words FOLDER_OR_PAGE   no phrase outside the evening-cut scope, packed days opened
  python -m demo.page_builder.checks.site FOLDER_OR_PAGE    script errors, outside addresses asked for, links, traces on screen
  python -m demo.page_builder.checks.live FOLDER_OR_PAGE    the optional Live view against made-up feeds served on a free port

Every check but `words` drives the installed Chrome through Playwright, which only these checks need (the builder runs on the
standard library). The scripts a check runs inside a page are the .js files beside these modules. Each check exits 1 when it
finds a fault.
"""
