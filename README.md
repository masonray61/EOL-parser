Authors: Aiden, Pablo 9/6/2026

**PROBLEM:**
    Battle lab software is to be tagged when their End-Of-Life date is passed, managing excel/csv files by hand is tedious and can be automated.
        └── Q: What is End-Of-Life (EOL)? 
                A: Think of it as a software expiration date for support. (EOL date indicates the termination of support)

**SOLUTION:**
    The method in which this will be acheived will be through pulling data cells and referencing them with respect to data pulled from public api resources like endoflife.date, large reference material to assign certain software with their appropriate EOL date. As well as application suites they're associated with.

**GOAL:**
    With their determined EOL date, we should simply take that date and append to each line detailing an individual software and mark the field where EOL would be with value(s) 'Y' or 'N' (Represents Yes and No for whether they've reached end of life)

**Dev-Cycle:**

*Given a csv file containing:*
Software name, & EOL date-

    We will be able to tag the software as Y (End of life) or N (Not End of life)

    If EOL date is null, an API call to endoflife.date should produce a date for most software.

    If software not found in endoflife.date:
        Use resources like NIST CPE Dictionary to guess the family/suite if contained inside of one (Then requery & tag [SHOULD BE AUTOMATED])
            └── If no further information then Flag with [REVIEW] in the date field
        For large subsets of data, software not found in endoflife.date should be appended to a list until the query is finished which will then prompt the lookup in NIST CPE Dictionary, then back through the endoflife.date API individually.

    To query through the data dynamically,

    IF EOL == Y then ignore, rows of software where EOL is null or N should be reviewed and processed.

    [FOR HARD REVIEW YOU CAN QUERY THE ENTIRE CSV THROUGH A SECONDARY METHOD]


*VISUALIZED:*

    [ IDENTIFY SOFTWARE ]
              |
    Is individual EOL Available?
    ├── YES ---> Tag with individual EOL
    |
    └── NO ---> Does it have a Parent Suite ID?
                        ├── YES ---> Tag with SUITE EOL
                        |
                        └── NO ---> [Fallback Method(s)]
                                            |
                                    Tag [REVIEW] for manual review
                                    or 
                                    Vendor Default

**Additional:**

Pandas has a lot of built in functionality to directly work with CSVs, but any data parsing tool can accomplish this as long as you properly through the columns/rows to find the appropriate data cells.
Not all software may have an EOL date, as many software don't anticipate terminating support, it's important to keep this in mind when seeing certain software not being tagged with Y or N.