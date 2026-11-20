#!/usr/bin/env python3
"""Query and edit the HameNews knowledge base. Examples:

  python kb.py seed                                   # load the agency list etc. (the daily run does this too)
  python kb.py show "Tasnim News Agency"
  python kb.py tied-to Iran --hops 2
  python kb.py add-claim "Iran International" funded_by "Saudi Arabia" --status reported \\
        --by "The Guardian" --source https://example.com/article --published 2018-10-31
  python kb.py add-claim "Iran International" funded_by "Saudi Arabia" --status denied \\
        --by "Iran International" --source https://example.com/statement
  python kb.py disputed
  python kb.py sql "SELECT subject_name, predicate, object_name, status FROM v_claims WHERE status='alleged'"
"""
from trendwatch.kb.cli import main

if __name__ == "__main__":
    main()
