# Vendored verbatim from the legacy repo's scripts/lintbasic.py for its
# tokenizer and helpers.  Do not edit here; re-copy when upstream changes.
r"""Static checks for Pick BASIC: uninitialized and write-only vars, labels,
CALL parameters.

Usage:
    python scripts/lintbasic.py LG.GET.CD.BRANCH
    python scripts/lintbasic.py LG.ORDER.MAINT,LG.COPY.PRD,src/BP/LG.DG.WEIGHTS
    python scripts/lintbasic.py --ignore 'GE*' LG.ORDER.MAINT
    python scripts/lintbasic.py -q "W4SUBORD*"          # wildcard
    python scripts/lintbasic.py -q "*"                  # every program found
    python scripts/lintbasic.py --format porcelain FOO  # one line per finding
    python scripts/lintbasic.py --no-unreferenced -q "*"    # variables only
    python scripts/lintbasic.py --no-uninitialized -q "*"   # labels and NEXTs
    python scripts/lintbasic.py --no-orphan-next -q "*"     # drop NEXT findings
    python scripts/lintbasic.py --no-param-check -q "*"     # skip the CALL check
    python scripts/lintbasic.py --no-undefined -q "*"       # skip missing labels
    python scripts/lintbasic.py --no-deadcode -q "*"        # skip unreachable code
    python scripts/lintbasic.py --no-dimcheck -q "*"        # skip the MAT/DIM check
    python scripts/lintbasic.py --no-unused-var -q "*"      # skip write-only vars

Programs may be named bare, given as a path, or matched with a `*` / `?`
wildcard, and several may be passed either comma-separated or as separate words.

Names and bare wildcards resolve against the CURRENT DIRECTORY first, then
src/BP.  So `lintbasic.py -q "*"` lints whatever directory you are standing in
-- a scratch directory of programs pulled off the server, say -- while a bare
pattern typed from elsewhere in the repo still finds src/BP.  A pattern holding a
slash or backslash is globbed against the filesystem as given, so `.\W4SUB*`
works too.  Overlapping patterns check each file only once.

Quote the pattern: PowerShell passes it through untouched, but bash would expand
it against the current directory first.  Pair a broad sweep with -q so only
programs with findings are printed.

Wildcard matches skip dotfiles and obviously non-BASIC extensions (.md, .ps1,
.py, ..) so that a sweep of a mixed directory does not report nonsense; naming
such a file explicitly still lints it.  Inside the repo, src/PROK, src/TEMPLATES,
src/MENU-ITEMS and src/DICT are refused rather than parsed -- PROC, binary W4
forms, and menu and dictionary records are not Pick BASIC.

The check is deliberately FLOW-INSENSITIVE.  It reports a name that is READ
somewhere in the program but never ASSIGNED anywhere in it.  That is exactly the
shape a variable-name typo makes, and it is the one shape that can be reported
with almost no false positives -- unlike "read before written on some path",
which drowns in GOTO/GOSUB noise in code this size.

A name counts as initialized when it is written or declared anywhere, by any of:

    assignment                 X = ..   X<1> = ..   X(3) = ..   X += ..
    SUBROUTINE/FUNCTION params SUBROUTINE FOO(A, B, MAT C)
    declarations               COMMON, DIM, EQU/EQUATE, DEFFUN
    read targets               READ/READV/READNEXT/MATREAD/OSREAD/INPUT/...
    handle targets             OPEN .. TO fv, SELECT .. TO list, GETLIST .. TO l
    result targets             LOCATE(..;pos), .. SETTING v, FIND .. SETTING a,v,s
                               EXECUTE .. CAPTURING/RETURNING/RTNLIST v
    rewriting statements       REMOVE, MATPARSE, MATBUILD, MAT a =, CONVERT .. IN v
    CALL arguments             Pick passes by reference, so a bare variable
                               argument may be an output parameter (--strict-call
                               turns this off)
    by-ref built-ins           submitRequest(..), UDOGetProperty(..) and friends

Two extra typo classes are reported alongside it: an `ORPHANED NEXT` (a `NEXT X`
with no `FOR X` anywhere -- `FOR A` / `NEXT B` is a real instance in the tree),
and, under --strict-init, names only ever written by `X<n>=` or `X += ..`.

A second, independent check runs over the same parse: an UNREFERENCED LABEL, a
`FOO:` or `9000:` statement label that no `GOTO`, `GOSUB`, `ON .. GOTO/GOSUB` or
`RETURN TO` in the program names.  Such a label is often just a dead section
marker, but it is also what a renamed or deleted branch leaves behind, and it is
how a GOSUB block that nothing calls any more shows up.  Labels are file-local
and UniVerse BASIC cannot build a branch at run time, so unlike a subroutine
this can be decided with certainty from the one program.  Labels defined inside
an $INCLUDE are not reported -- their line numbers belong to another file --
but branches written there do count as references.  STARTMACRO and ENDMACRO are
exempt: they are the AccuTerm macro-recorder hooks, pasted into hundreds of
programs as a pair whether or not that copy GOSUBs both halves.

Its mirror runs alongside it: an UNDEFINED LABEL, a branch naming a label the
program never defines.  UniVerse rejects that at COMPILE time rather than run
time, so a hit means the program cannot currently be cataloged -- it is dead
code, or nobody has recompiled it since the label was deleted.  That also makes
the finding count a check on this parser rather than on the source: a handful
across the whole tree is plausible, hundreds would mean the branch scanning is
wrong.  The one false positive available is a label arriving through an
unresolvable $INCLUDE, which is what the unresolved-include warning is for.

Last, needing no lookup outside the file at all: DEAD CODE, a statement control
cannot reach.  The walk carries a single bit -- does the statement above hand
control down? -- and takes any label or block keyword (END, ELSE, CASE, LOOP,
REPEAT, NEXT, ..) as proof that something may branch in.  Sound without a
control-flow graph, again because UniVerse cannot compute a branch target: a
statement with no label between it and an unconditional GOTO, RETURN, STOP,
ABORT or CHAIN is genuinely unreachable.  Only the head of each dead run is
reported, so a forty-line dead block costs one finding.  One shape is let
through on purpose: a lone RETURN directly under an unconditional GO, which
this tree leaves in deliberately so that a stretch later promoted to a
subroutine already has its exit written.

The mirror of the uninitialized check is WRITE-ONLY, a name this program
assigns and then never reads.  On its own that is only untidy, but it is also
what is left behind when the code that used to read the value is deleted or
commented out -- `HAZFLG=""` survives in 90DAYHAZRPT while both lines that read
it sit behind a `*` -- and it is the second half of the typo the uninitialized
check finds from the other end: write `TOTAL` and read `TOATL` and both names
are reported, one each way.

It is deliberately narrower than "in `defs` but not in `reads`", which is most
of a report and almost none of it useful.  Only a plain `NAME = ..` in this
file counts as the write.  A name written any OTHER way is left alone, because
each of those has a reader this program cannot see: a SUBROUTINE or FUNCTION
parameter is how the caller gets its answer back (`SUBROUTINE LG.UPC.CHECK(CDBACK,IDIN)`
assigns CDBACK twice and reads it never -- that is the whole point of it), COMMON is
shared with whatever CHAINs here next, a CALL argument is passed by reference so
the callee may be the only reader, and the spare `F1,F2,F3,F4,F5` file variables
every `*OPEN.FILE`-style call takes are required positionally whether this
program wants them or not.  EQU, DIM, FOR control variables and READ / SETTING /
LOCATE targets are excluded for the same reason.  An assignment reached through
an $INCLUDE never counts either -- its line number belongs to another file -- so
it can only ever silence a finding, never raise one.

`X += 1` is not reported: the compound form reads X before it writes it, so the
name lands in `reads` on its own.

A separate check catches MAT used on a name that nothing dimensions.  MATREAD,
MATWRITE, MATPARSE, MATBUILD .. FROM, `MAT a =` and `CALL SUB(MAT a)` all need
a real matrix; a name that only ever holds a dynamic array is a different type
entirely.  Dimensions come from DIM, from COMMON with a subscript, and from a
MAT parameter in the SUBROUTINE header, includes and all -- and because a DIM
can sit inside an include this checkout cannot resolve, the check goes quiet
for a program with an unresolved $INCLUDE rather than guess.

Two subtleties do the real work.  A THEN or ELSE makes the whole rest of the
line conditional, semicolons and all -- `MATREAD .. ELSE X=0 ; RETURN` returns
only when the read fails -- so no line carrying a boundary word can end the
flow; missing that turns the commonest idiom in the tree into thousands of
false positives.  And declarations (EQU, COMMON, DIM, ..) are compile-time,
neither reached nor missed, so the walk steps over them rather than calling a
block of EQUs after a STOP dead.  What it will NOT find is a block unreachable
because nothing branches to its label -- that needs the graph, and the
unreferenced-label check is the partial stand-in.  Both limits are misses, not
false alarms.

A third check leaves the one program behind: MISMATCHED PARAMETERS, a `CALL`
whose argument count does not match the callee's `SUBROUTINE` header.  UniVerse
fails these at run time rather than at compile time -- the call raises "Program
.. has been called with an incorrect number of arguments" the first time that
line is reached -- so they hide in rarely taken branches, which is what makes
them worth finding statically.  The callee is looked up by name in the current
directory and then src/BP, the same order a program argument resolves in, and
its header is read once per run and cached.

A callee with no header to check against is not given up on.  Plenty are
missing -- the ATGUI* GUI library and WOBJ live outside this repo, and
first-party subroutines drift out of the checkout too (SUB.CLEAR.M.LINE has
thirty call sites in LG.ORDER.MAINT and no file) -- so for those the program's own
other calls stand in for the header.  UniVerse has no optional parameters, so if
twenty-nine sites pass seven arguments and one passes none, one of them is
wrong, and it is not the twenty-nine.  Only a strict plurality is reported
against: two sites disagreeing one-to-one prove a bug without saying which side
is the bug, and naming both would only be noise.

What is never reported is a callee nothing can be said about: called from one
place only, or `CALL @VAR(..)`, which does not resolve at all.  A resolved file
whose first statement is not a SUBROUTINE header -- a main program, a FUNCTION,
a data record parked in src/BP -- falls back to the same call-site evidence.

Every check runs by default and each has an off switch: --no-uninitialized drops
the variable findings (and the --strict-init variant of them), --no-unused-var
drops the write-only findings, --no-orphan-next drops the NEXT findings,
--no-unreferenced and --no-undefined drop the two label findings, --no-deadcode
drops the unreachable-code findings, and --no-param-check drops the CALL
findings.  All but the last share the one parse
and so only suppress output; --no-param-check also skips building the callee
index and reading the callee sources, the one flag that saves real time.

Caveats worth knowing before trusting a report:
  * An unresolvable $INCLUDE hides whatever it declares.
  * Pick PROCs are skipped -- they are not BASIC.  Non-BASIC text that happens to
    live in src/BP (MENU-MAP, ..) cannot be detected and will produce
    nonsense.

Exit status: 0 when every program is clean, 1 when anything was reported, 2 when
a named program could not be found -- or always 0 under --exit-zero, which is
what .vscode/tasks.json uses so findings arrive via the problem matcher instead
of looking like a crashed task.
"""

import argparse
import collections
import glob
import os
import re
import sys

# ---------------------------------------------------------------------------
# lexer
# ---------------------------------------------------------------------------

# UniVerse identifiers: a letter, then letters / digits / . $ % _
_TOK = re.compile(r"""
      [ \t\r\f]+
    | "[^"\n]*"?
    | '[^'\n]*'?
    | \\[^\\\n]*\\?
    | @[A-Za-z][A-Za-z0-9._$%]*
    | @
    | [A-Za-z][A-Za-z0-9._$%]*
    | [0-9][0-9.]*
    | \.[0-9][0-9.]*
    | :=|\+=|-=|\*=|/=|<=|>=|<>|><|=<|=>
    | .
""", re.VERBOSE)

# After one of these words a brand new statement starts on the same line, so
# `IF A THEN B = 1` must not be read as a comparison against B.
BOUNDARY = frozenset("THEN ELSE DO LOCKED LOOP REPEAT".split())

# A branch keyword may be run straight into its numeric label with no space --
# `GOSUB300`, `GO20` -- which UniVerse's lexer splits and a plain identifier
# pattern does not.  Anchored and exact on purpose: the dotted label
# `GUI.FRMMAIN.POPMENU1.GOTO2` and the string 'GOTO2' must be left whole.
_GLUED_BRANCH = re.compile(r"^(GOSUB|GOTO|GO)([0-9]+)$")


def tokenize(line):
    """Split one source line into statement segments of (kind, text, col) tuples."""
    return [seg for _opener, seg in tokenize_marked(line)]


def tokenize_marked(line):
    """tokenize(), but each segment is paired with the token that opened it.

    The opener is None for the first statement on a line, ";" for one following
    a semicolon, and the BOUNDARY word otherwise.  Only that distinction can
    separate the `GOTO 100` that ends the flow of control from the one in
    `IF X THEN GOTO 100`, which ends nothing.

    Comments are dropped here rather than in a separate pass, because `*`, `!`
    and `REM` only start a comment at the beginning of a statement -- which is
    exactly the state this scanner already has to track.
    """
    segments = [[]]
    openers = [None]
    at_start = True
    depth = 0
    i, n = 0, len(line)
    while i < n:
        m = _TOK.match(line, i)
        text = m.group(0)
        col = i + 1
        i = m.end()
        c = text[0]

        if c in " \t\r\f":
            continue

        if c in "\"'\\":
            # UniVerse accepts " ' and \ as string delimiters, all interchangeable
            segments[-1].append(("STR", text, col))
            at_start = False
        elif c == "@":
            segments[-1].append(("SYS", text.upper(), col))
            at_start = False
        elif c.isalpha():
            word = text.upper()
            if at_start and word == "REM" and line[i:i + 1] != "(":
                break                                   # REM <text>
            glued = _GLUED_BRANCH.match(word)
            if glued:
                # `GOSUB300` -> GOSUB, 300
                segments[-1].append(("ID", glued.group(1), col))
                segments[-1].append(("NUM", glued.group(2),
                                     col + len(glued.group(1))))
                at_start = False
                continue
            segments[-1].append(("ID", word, col))
            # A boundary word is only a boundary when it is being used as the
            # keyword.  `LOOP:` opening a statement is a label -- seven programs
            # in src/BP branch to one -- and splitting there would hide both the
            # label and the rest of the line.  `:=` is an assignment, not a
            # label's colon.
            labelled = (at_start and line[i:i + 1] == ":"
                        and line[i:i + 2] != ":=")
            if word in BOUNDARY and not labelled:
                segments.append([])
                openers.append(word)
                at_start = True
            else:
                at_start = False
        elif c.isdigit() or (c == "." and len(text) > 1):
            # A number as the very first token of a line is an old-style
            # statement label (`100  READNEXT ID ELSE ..`, `99* HEADER`), so the
            # statement -- and any comment marker -- begins after it.
            label = at_start and len(segments) == 1 and not segments[0]
            segments[-1].append(("NUM", text, col))
            at_start = label
        else:
            if at_start and text in ("*", "!"):
                break                                   # whole-statement comment
            if text in ("(", "["):
                depth += 1
            elif text in (")", "]"):
                depth -= 1
            elif text == ";" and depth <= 0:
                segments.append([])
                openers.append(";")
                at_start = True
                continue
            segments[-1].append(("OP", text, col))
            # `LABEL:` / `9999:` starts a fresh statement, so a `*` right after
            # the colon is a comment and not a multiplication.
            at_start = (text == ":" and depth <= 0 and len(segments[-1]) == 2
                        and segments[-1][0][0] in ("ID", "NUM"))

    return [(o, s) for o, s in zip(openers, segments) if s]


# ---------------------------------------------------------------------------
# vocabulary -- nothing named here is ever treated as a variable
# ---------------------------------------------------------------------------

KEYWORDS = frozenset("""
ABORT ABORTE ABORTM AFTER AND ARG ARG. ASSIGN AT BEFORE BEGIN BREAK BSCAN BY
CALL CAPTURING CASE CAT CHAIN CLEAR CLEARDATA CLEARFILE CLEARINDEX CLEARPROMPTS
CLEARSELECT CLOSE CLOSEDEV CLOSESEQ COM COMMIT COMMON CONTINUE CONVERT CREATE
CRT DATA DEBUG DEFC DEFCS DEFFUN DEFINE DEL DELETE DELETELIST DELETEU DIM
DIMENSION DISPLAY DIV DO EACH ECHO ELSE END ENTER EQ EQU EQUATE ERROR EXEC
EXECUTE EXIT FILELOCK FILEUNLOCK FIND FINDSTR FLUSH FOOTING FOOTINGE FOOTINGN
FOR FORMLIST FROM FUNCTION GE GET GETLIST GETX GO GOSUB GOTO GT HEADING HEADINGE
HEADINGN HUSH IF IN INCLUDE INPUT INPUTCLEAR INPUTCTRL INPUTDISP INPUTERR
INPUTIF INPUTNULL INPUTTRAP INS INSERT ISOLATION KEYEDIT KEYEXIT KEYTRAP LE
LENGTH LET LIT LITERALLY LOCAL LOCATE LOCK LOCKED LOOP LT MAT MATBUILD MATCH
MATCHES MATPARSE MATREAD MATREADL MATREADU MATWRITE MATWRITEL MATWRITEU NAP NE
NEXT NOBUF NULL OFF ON OPEN OPENCHECK OPENDEV OPENINDEX OPENPATH OPENSEQ OR
OSBOPEN OSBREAD OSBWRITE OSCLOSE OSDELETE OSOPEN OSREAD OSWRITE OTHERWISE PAGE
PASSDATA PASSLIST PAUSE PERFORM PRECISION PRINT PRINTER PRINTERR PROCREAD
PROCWRITE PROGRAM PROMPT RANDOMIZE READ READBLK READFL READL READLIST READNEXT
READSEQ READT READU
READV READVFL READVL READVU RELEASE REM REPEAT RESET RETURN RETURNING REWIND
ROLLBACK RQM RTNLIST RUN SELECT SELECTE SELECTINDEX SELECTN SELECTV SEND SENDX SETINDEX
SETTING SLEEP SSELECT STEP STOP STOPE STOPM SUBROUTINE THEN TIMEOUT TO
TRANSACTION TRAP UNIT UNLOCK UNTIL USING WAKE WEOF WEOFSEQ WHILE WRITE WRITEBLK
WRITEFL WRITELIST WRITESEQ WRITESEQF WRITET WRITEU WRITEV WRITEVFL WRITEVU
""".split())

# Intrinsic functions.  These matter because `FOO(1)` is ambiguous between a
# function call and an array reference: without a list of the intrinsics, every
# LEN() / OCONV() would look like an undeclared array.
INTRINSICS = frozenset("""
ABS ABSS ACOS ADDS ALPHA ANDS ASCII ASIN ASSIGNED ATAN BITAND BITCHANGE
BITCHECK BITLOAD BITNOT BITOR BITRESET BITSET BITTEST BITXOR BYTE BYTELEN
BYTETYPE BYTEVAL CATS CHANGE CHAR CHARS CHECKSUM COL1 COL2 COMPARE COS COSH
COUNT COUNTS CRC32 DATE DCOUNT DECRYPT DESCRINFO DIGEST DIR DIVS DOWNCASE
DQUOTE DROUND
DTX EBCDIC ENCODE ENCRYPT EQS EREPLACE EXCHANGE EXP EXTRACT FADD FCMP FDIV FFIX
FFLT FIELD FIELDS FIELDSTORE FILEINFO FIX FMT FMTS FMUL FOLD FSUB GES GETENV
GETREM GROUP GTS HMAC ICONV ICONVS IFS INDEX INDEXS INDICES INMAT INT ISNULL
ISNV
ITYPE KEYIN LEFT LEN LENS LES LOCALEINFO LOWER LTS MATBUILDS MATCHFIELD MAXIMUM
MINIMUM MOD MODS MULS NEG NEGS NES NOT NOTS NUM NUMS OCONV OCONVS ORS PWR QUOTE
RAISE RECORDLOCKED REMOVE REPLACE REUSE RIGHT RND SADD SDIV SEEK SELECTINFO
SENTENCE SEQ SEQS SETREM SIN SINH SMUL SOUNDEX SPACE SPACES SPLICE SQRT SQUOTE
SSUB STATUS STR STRS SUBR SUBS SUBSTRINGS SUM SUMMATION SWAP SYSTEM TAN TANH
TIME TIMEDATE TRANS TRIM TRIMB TRIMBS TRIMF TRIMFS TRIMS UNASSIGNED UNICHAR
UNICHARS UNILEN UNISEQ UPCASE XLATE XTD
""".split())

# UniVerse HTTP / socket / XML / UDO built-ins.  These are ordinary function
# calls, but their trailing arguments are by-reference OUTPUTS -- e.g.
# `stat = createSecureRequest(url, method, handle, ctx)` fills in `handle`.  So
# their bare-variable arguments count as definitions, the way CALL's do.
BYREF_FUNCS = frozenset("""
ACCEPTCONNECTION ADDAUTHENTICATIONRULE ADDCERTIFICATE ADDREQUESTPARAMETER
CLOSESOCKET
CREATECERTIFICATE CREATELOADBALANCEGROUP CREATEREQUEST CREATESECUREREQUEST
CREATESECURITYCONTEXT DELETELOADBALANCEGROUP GENERATECERTIFICATEREQUEST
GENERATESECUREKEY GETCIPHERSUITE GETHTTPDEFAULT GETRESPONSEHEADER
GETSOCKETINFORMATION
GETSOCKETOPTIONS INITSERVERSOCKET LOADSECURITYCONTEXT OPENSECURESOCKET
OPENSOCKET PROTOCOLLOGGING READSOCKET SAVESECURITYCONTEXT
SETAUTHENTICATIONDEPTH SETHTTPDEFAULT SETREQUESTHEADER SETSOCKETOPTIONS
SHOWSECURITYCONTEXT SUBMITREQUEST WRITESOCKET
XDOMADDCHILD XDOMAPPEND XDOMATTRIBUTESET XDOMCLONE XDOMCLOSE XDOMCREATE
XDOMCREATENODE XDOMEVALUATE XDOMGETNODEVALUE XDOMINSERT XDOMLOCATE XDOMOPEN
XDOMREMOVE XDOMREPLACE XDOMSETNODEVALUE XDOMTRANSFORM XDOMWRITE
XMAPAPPENDREC XMAPCLOSE XMAPOPEN XMAPREADNEXT XMAPTOXML XMLGETERROR
UDOALLOC UDOARRAYADDITEM UDOARRAYDELETEITEM UDOARRAYGETITEM UDOARRAYGETSIZE
UDOARRAYSETITEM UDOCLONE UDOCREATE UDOFREE UDOGETNEXTPROPERTY UDOGETPROPERTY
UDOGETPROPERTYNAMES UDOGETTYPE UDOREAD UDOSETPROPERTY UDOWRITE
""".split())

NON_VARIABLES = KEYWORDS | INTRINSICS | BYREF_FUNCS


def is_var(tok):
    return tok[0] == "ID" and tok[1] not in NON_VARIABLES


# ---------------------------------------------------------------------------
# statement analysis
# ---------------------------------------------------------------------------

ASSIGN_OPS = frozenset(("=", ":=", "+=", "-=", "*=", "/="))
OPEN_BRACKETS = {"(": ")", "[": "]", "<": ">"}
CLOSE_BRACKETS = frozenset((")", "]", ">"))

# statements where the name after TO is written, not read
TO_DEFINES = frozenset("""
OPEN OPENSEQ OPENPATH OPENDEV OPENCHECK OSOPEN OSBOPEN SELECT SSELECT SELECTV
SELECTE GETLIST FORMLIST
""".split())

# words that introduce a written variable in almost any statement
SETTING_WORDS = frozenset(("SETTING", "CAPTURING", "RETURNING", "RTNLIST"))

# statements whose leading operand is the variable being filled in
READ_LIKE = frozenset("""
READ READU READL READV READVU READVL READT READBLK READSEQ READFL READVFL
READLIST READNEXT MATREAD MATREADU MATREADL MATPARSE MATBUILD MAT OSREAD
OSBREAD INPUT INPUTIF PROCREAD BSCAN STATUS
""".split())

# ...of those, the ones that take a comma-separated list of targets
MULTI_TARGET = frozenset(("READNEXT", "BSCAN"))

# Statements whose FIRST operand has to be a dimensioned array.  `MATBUILD s
# FROM a` is the odd one out -- there the matrix follows FROM -- so it is
# handled separately rather than listed here.
MAT_STATEMENTS = frozenset("""
MAT MATREAD MATREADL MATREADU MATWRITE MATWRITEL MATWRITEU MATPARSE
""".split())

# Control never falls out of one of these into the next statement.  ON..GOTO is
# deliberately absent: an index outside the label list falls straight through.
TERMINATORS = frozenset("""
ABORT ABORTE ABORTM CHAIN GO GOTO RETURN STOP STOPE STOPM
""".split())

# Compile-time declarations.  Control never "reaches" one of these at all, so
# the walk steps over them rather than calling them dead: a block of EQUs after
# a STOP is perfectly ordinary, and two programs in src/BP open exactly that way.
DECLARATIONS = frozenset("""
COM COMMON DEFFUN DIM DIMENSION EQU EQUATE FUNCTION PROGRAM SUBROUTINE
""".split())

# ...but two of those declarations are also ENTRY POINTS.  UniVerse binds a CALL
# straight to a SUBROUTINE or FUNCTION statement, so control arrives there from
# outside the program and a run of unreachable code ends.  LG.ORDER.MAINT carries two
# of them below the main body -- SUB.CLEAR.M.LINE and SUB.CALC.GROSSP.AND.UNIT.DISC,
# broken out in May 2026 and reached only by CALL.  Without this they read as dead
# code after the RETURN above them, and the obvious "fix" deletes live subroutines.
ENTRY_POINTS = frozenset("""
FUNCTION SUBROUTINE
""".split())

# ...and at one of these, control can arrive from somewhere other than the
# statement above, so a run of unreachable code ends.  Deliberately broad: a
# missed rejoin invents dead code, while a spurious one only costs a finding.
# The AccuTerm GUI macro-recorder hooks.  Roughly 512 programs paste in the
# same STARTMACRO:/ENDMACRO: pair of GOSUB blocks, and plenty of them call only
# one of the two -- 312 unreferenced-label findings that say nothing about the
# program.  The boilerplate is meant to be there whether or not this copy uses
# it, so neither name is ever reported as unreferenced.
MACRO_LABELS = frozenset(("STARTMACRO", "ENDMACRO"))

REJOIN = frozenset("""
BEGIN CASE CONTINUE ELSE END LOCKED LOOP NEXT REPEAT THEN UNTIL WHILE
""".split())

# words that end the target list of a read-like statement
STOP_WORDS = frozenset("""
FROM TO ON AT IN ELSE THEN SETTING USING BY LENGTH BEFORE AFTER CAPTURING
RETURNING RTNLIST PASSLIST PASSDATA LOCKED TIMEOUT
""".split())


class Analysis(object):
    """Definitions, reads and labels accumulated over a program and its includes."""

    def __init__(self, strict_call=False, strict_init=False):
        self.strict_call = strict_call
        self.strict_init = strict_init
        # Every table stores NAME -> (line, col) of the first occurrence.  The
        # column matters for editor integration: a diagnostic should underline
        # the name itself rather than the whole line.
        self.defs = {}        # first write
        self.weak_defs = {}   # first write, subscripted/compound assign only
        self.reads = {}       # first read
        # The write-only check needs to know HOW a name was written, not merely
        # that it was.  `assigns` holds the names a plain `NAME = ..` in this
        # file wrote; `other_defs` collects every other way a name gets written
        # -- SUBROUTINE parameter, COMMON, EQU, DIM, FOR control variable, READ
        # or SETTING target, CALL argument -- because each of those has a reader
        # outside this program, or none at all, and reporting them is noise.
        self.assigns = {}     # first plain assignment, this file only
        self.other_defs = set()   # names written by anything but a plain assign
        self.labels = set()
        # Labels are tracked twice over: `labels` is every label name seen
        # anywhere, includes and all, which is what keeps a name that doubles as
        # a label out of the variable findings; `label_defs` holds only the ones
        # declared in this program, the only ones whose line number is worth
        # reporting.
        self.label_defs = {}      # KEY -> (line, col, text), this file only
        self.label_all_defs = set()   # KEYs defined anywhere, includes and all
        self.label_refs = set()   # KEYs named by GOTO / GOSUB / ON .. / RETURN TO
        self.label_ref_sites = {}     # KEY -> (line, col, text), this file only
        self.local_funcs = set()
        self.calls = []           # (name, nargs, line, col), this file only
        self.dead = {}            # line -> (col, terminator line, terminator word)
        self.for_vars = set()     # control variables of FOR statements
        self.dims = set()         # names given a dimension by DIM/COMMON/MAT param
        self.mat_uses = []        # (name, line, col, keyword), this file only
        self.next_vars = {}       # first NEXT naming it
        self.unresolved_includes = []
        self.resolved_includes = []
        self.not_basic = False

    def define(self, tok, line, weak=False, assign=False):
        if not is_var(tok):
            return
        table = self.weak_defs if weak else self.defs
        table.setdefault(tok[1], (line, tok[2]))
        # A weak write only reaches here under --strict-init, where it is the
        # partial-init check's business; reporting it write-only as well would
        # name the same line twice.
        if assign and not weak:
            self.assigns.setdefault(tok[1], (line, tok[2]))
        else:
            self.other_defs.add(tok[1])

    def read(self, tok, line):
        if not is_var(tok):
            return
        self.reads.setdefault(tok[1], (line, tok[2]))

    def read_all(self, toks, line):
        for t in toks:
            self.read(t, line)

    def define_label(self, tok, line, quiet=False):
        # `label_all_defs` answers "does this label exist at all", so an include's
        # labels belong in it; `label_defs` drives the unreferenced report and so
        # holds only this file's, whose line numbers point somewhere useful.
        if tok[0] == "ID":
            self.labels.add(tok[1])
        self.label_all_defs.add(_label_key(tok))
        if not quiet:
            self.label_defs.setdefault(_label_key(tok), (line, tok[2], tok[1]))

    def ref_label(self, tok, line, quiet=False):
        self.label_refs.add(_label_key(tok))
        if not quiet:
            self.label_ref_sites.setdefault(_label_key(tok), (line, tok[2], tok[1]))

    def ref_labels(self, toks, line, quiet=False):
        """Record every label named by a branch operand list.

        Covers `GOTO 100`, `GO TO 100`, `GOSUB DONE:` and the comma-separated
        `ON X GOTO 10,20,30`; a trailing colon is part of neither name.
        """
        if toks and _is_word(toks[0], "TO"):
            toks = toks[1:]                           # GO TO 100
        for part in _split_commas(toks):
            if part and part[0][0] in ("ID", "NUM"):
                self.ref_label(part[0], line, quiet)


# -- little token helpers ----------------------------------------------------

def _label_key(tok):
    """Match key for a label token.

    Names are already uppercased by the lexer.  A numeric label is matched on
    its value rather than its text, so `GOSUB 0100` reaches `100:`.
    """
    if tok[0] == "NUM":
        return tok[1].lstrip("0") or "0"
    return tok[1]


def _is_op(tok, text):
    return tok[0] == "OP" and tok[1] == text


def _is_word(tok, word):
    return tok[0] == "ID" and tok[1] == word


def _is_bare_return(marked):
    """True when the whole line is a lone RETURN -- no TO, no value, no other
    statement beside it.  Comments are already gone by the time tokenizing ends,
    so `RETURN ;* done` still counts."""
    tokens = [tok for _opener, seg in marked for tok in seg]
    return len(tokens) == 1 and _is_word(tokens[0], "RETURN")


def _lhs_assign(toks):
    """If toks looks like `VAR[subscripts] <assign-op> ...`, return
    (index_of_assign_token, op_text, partial); otherwise None.

    Tokens 1..index are subscript expressions, everything after index is the
    right-hand side.  `partial` is True when the statement only writes part of
    the variable (`X<n>=`, `X(n)=`) or reads it back (`X += ..`).

    The lexer glues `>=` into one token, so `DOWNFILE<-1>=CTRL` closes its angle
    group and assigns in the same token; that is unpicked here.
    """
    if not toks or toks[0][0] != "ID":
        return None
    i, n, partial = 1, len(toks), False
    while i < n and toks[i][0] == "OP" and toks[i][1] in OPEN_BRACKETS:
        partial = True
        depth = 0
        closed = False
        while i < n:
            t = toks[i]
            if t[0] == "OP":
                if t[1] in OPEN_BRACKETS:
                    depth += 1
                elif t[1] in CLOSE_BRACKETS:
                    depth -= 1
                    if depth == 0:
                        i += 1
                        closed = True
                        break
                elif t[1] == ">=" and depth == 1:
                    return i, "=", True         # `X<n>=` -- close and assign
            i += 1
        if not closed:
            return None                         # unbalanced; not an assignment
    if i < n and toks[i][0] == "OP" and toks[i][1] in ASSIGN_OPS:
        op = toks[i][1]
        return i, op, partial or op != "="
    return None


def _split_commas(toks):
    """Split a token list on top-level commas."""
    parts, cur, depth = [], [], 0
    for t in toks:
        if t[0] == "OP":
            if t[1] in OPEN_BRACKETS:
                depth += 1
            elif t[1] in CLOSE_BRACKETS:
                depth -= 1
            elif t[1] == "," and depth <= 0:
                parts.append(cur)
                cur = []
                continue
        cur.append(t)
    parts.append(cur)
    return [p for p in parts if p]


def _inside_parens(toks):
    """Contents of the first top-level (...) group."""
    for i, t in enumerate(toks):
        if _is_op(t, "("):
            depth, out = 0, []
            for t2 in toks[i:]:
                if _is_op(t2, "("):
                    depth += 1
                    if depth == 1:
                        continue
                elif _is_op(t2, ")"):
                    depth -= 1
                    if depth == 0:
                        return out
                out.append(t2)
            return out
    return []


def _upto_stop(toks):
    for i, t in enumerate(toks):
        if t[0] == "ID" and t[1] in STOP_WORDS:
            return toks[:i]
    return list(toks)


def _find_word(toks, word):
    for i, t in enumerate(toks):
        if _is_word(t, word):
            return i
    return None


def _top_level(toks, op):
    """Indexes of every occurrence of `op` outside any bracket group."""
    depth, found = 0, []
    for i, t in enumerate(toks):
        if t[0] == "OP":
            if t[1] in OPEN_BRACKETS:
                depth += 1
            elif t[1] in CLOSE_BRACKETS:
                depth -= 1
            elif t[1] == op and depth <= 0:
                found.append(i)
    return found


def _first_ident(toks):
    for i, t in enumerate(toks):
        if t[0] == "ID":
            return i
    return None


# -- the classifier ----------------------------------------------------------

def analyze(toks, line, an, quiet_reads=False, line_start=False):
    """Classify one statement.

    quiet_reads=True harvests declarations out of an include file without
    letting that file's own reads become findings for the caller.

    line_start=True marks the first statement of a source line, the only place
    a bare number is a label rather than a branch target.
    """
    if not toks:
        return

    def rd(items):
        if not quiet_reads:
            an.read_all(items, line)

    # compiler directive ($OPTIONS, $MAP, ...); $INCLUDE handled by the scanner
    if _is_op(toks[0], "$"):
        return

    # statement label -- `FOO:`, `100:`, or a bare numeric label `100`
    if len(toks) >= 2 and toks[0][0] in ("ID", "NUM") and _is_op(toks[1], ":"):
        an.define_label(toks[0], line, quiet_reads)
        analyze(toks[2:], line, an, quiet_reads)
        return
    if toks[0][0] == "NUM":
        # A bare number leading a source line is a label.  Anywhere else it is a
        # value, not a branch: UniVerse spells the jump `GOTO 100` -- the bare
        # `IF c THEN 100` form appears nowhere in this tree -- while the
        # `X = IF c THEN 1 ELSE 2` expression drops plain numbers into exactly
        # the position a THEN-goto would occupy.  Reading those as labels
        # invents references, and undefined ones at that.
        if line_start:
            an.define_label(toks[0], line, quiet_reads)
        analyze(toks[1:], line, an, quiet_reads)
        return

    head = toks[0][1] if toks[0][0] == "ID" else None
    rest = toks[1:]

    # Names this statement requires to be dimensioned.  Collected for every
    # statement, checked later against everything DIM declared anywhere --
    # UniVerse does not care whether the DIM sits above or below the use.
    if not quiet_reads:
        if head in MAT_STATEMENTS and rest and rest[0][0] == "ID":
            an.mat_uses.append((rest[0][1], line, rest[0][2], head))
        elif head == "MATBUILD":
            for i, t in enumerate(rest):
                if (_is_word(t, "FROM") and i + 1 < len(rest)
                        and rest[i + 1][0] == "ID"):
                    an.mat_uses.append((rest[i + 1][1], line,
                                        rest[i + 1][2], "MATBUILD"))
                    break
        # `CALL SUB(MAT A, B)` and `MAT A = MAT B` -- a MAT anywhere past the
        # statement head marks the name after it.
        if head in ("CALL", "MAT") or head in MAT_STATEMENTS:
            for i in range(1, len(toks) - 1):
                if _is_word(toks[i], "MAT") and toks[i + 1][0] == "ID":
                    an.mat_uses.append((toks[i + 1][1], line,
                                        toks[i + 1][2], head or "MAT"))

    # SETTING / CAPTURING / RETURNING / RTNLIST targets, in any statement
    for i, t in enumerate(toks):
        if t[0] == "ID" and t[1] in SETTING_WORDS and i + 1 < len(toks):
            for part in _split_commas(_upto_stop(toks[i + 1:])):
                if len(part) == 1:
                    an.define(part[0], line)

    # by-reference outputs of the built-in HTTP / socket / XML / UDO functions
    for i, t in enumerate(toks):
        if (t[0] == "ID" and t[1] in BYREF_FUNCS
                and i + 1 < len(toks) and _is_op(toks[i + 1], "(")):
            for part in _split_commas(_inside_parens(toks[i + 1:])):
                if len(part) == 1 and part[0][0] == "ID":
                    an.define(part[0], line)

    # ---- declarations ------------------------------------------------------
    if head in ("SUBROUTINE", "FUNCTION", "PROGRAM"):
        for part in _split_commas(_inside_parens(rest)):
            matted = any(_is_word(t, "MAT") for t in part)
            part = [t for t in part if not _is_word(t, "MAT")]
            if part:
                an.define(part[0], line)
                if matted and part[0][0] == "ID":
                    an.dims.add(part[0][1])
        return

    if head in ("COMMON", "COM"):
        body = rest
        if body and _is_op(body[0], "/"):
            for j in range(1, len(body)):
                if _is_op(body[j], "/"):
                    body = body[j + 1:]
                    break
        for part in _split_commas(body):
            part = [t for t in part if not _is_word(t, "MAT")]
            if not part:
                continue
            an.define(part[0], line)
            # `COMMON /AREA/ A(10), B` dimensions A but not B.
            if (part[0][0] == "ID" and len(part) > 1
                    and _is_op(part[1], "(")):
                an.dims.add(part[0][1])
            rd(part[1:])
        return

    if head in ("DIM", "DIMENSION"):
        for part in _split_commas(rest):
            an.define(part[0], line)
            if part[0][0] == "ID":
                an.dims.add(part[0][1])
            rd(part[1:])
        return

    if head in ("EQU", "EQUATE"):
        for part in _split_commas(rest):
            cut = len(part)
            for j, t in enumerate(part):
                if t[0] == "ID" and t[1] in ("TO", "LIT", "LITERALLY"):
                    cut = j
                    break
            if cut:
                an.define(part[0], line)
            rd(part[cut + 1:])
        return

    if head == "DEFFUN":
        if rest and rest[0][0] == "ID":
            an.local_funcs.add(rest[0][1])
        return

    # ---- control flow ------------------------------------------------------
    # `CASE ST="NY" GOSUB LABOR.SET.EXC` -- a branch may follow the CASE
    # expression on the same line with no semicolon between them, so its
    # operand is a label and not the tail of the condition.  CASE cannot join
    # BOUNDARY: the split falls after the expression, not after the keyword,
    # and only a branch keyword marks that point without parsing the
    # expression -- GOTO, GOSUB and GO are reserved, so none of the three can
    # appear inside one.  Anything else trailing a CASE in this tree is
    # semicolon-separated and already split by the lexer, so a CASE with no
    # branch keeps falling through to the ordinary expression read.
    if head == "CASE":
        cut, depth = None, 0
        for j, t in enumerate(rest):
            if t[0] == "OP":
                if t[1] in OPEN_BRACKETS:
                    depth += 1
                elif t[1] in CLOSE_BRACKETS:
                    depth -= 1
            elif (t[0] == "ID" and depth <= 0
                    and t[1] in ("GOTO", "GOSUB", "GO")):
                cut = j
                break
        if cut is not None:
            rd(rest[:cut])
            analyze(rest[cut:], line, an, quiet_reads)
            return

    if head in ("GOTO", "GOSUB", "GO"):
        an.ref_labels(rest, line, quiet_reads)        # operands are labels
        return

    if head == "ON":
        if rest and _is_word(rest[0], "ERROR"):
            analyze(rest[1:], line, an, quiet_reads)
            return
        cut = len(rest)
        for j, t in enumerate(rest):
            if t[0] == "ID" and t[1] in ("GOTO", "GOSUB", "GO"):
                cut = j
                break
        rd(rest[:cut])
        an.ref_labels(rest[cut + 1:], line, quiet_reads)   # ON X GOTO 10,20,30
        return

    if head == "RETURN":
        cut = _find_word(rest, "TO")
        if cut is None:
            rd(rest)
        else:
            rd(rest[:cut])
            an.ref_labels(rest[cut + 1:], line, quiet_reads)  # RETURN TO 1
        return

    if head == "FOR":
        if rest:
            an.define(rest[0], line)
            if is_var(rest[0]):
                an.for_vars.add(rest[0][1])
        rd(rest[1:])
        return

    if head == "NEXT":
        # `NEXT X` is not really a read of X, and an X with no matching `FOR X`
        # is its own kind of typo -- reported separately rather than as an
        # uninitialized variable.
        if rest and is_var(rest[0]):
            an.next_vars.setdefault(rest[0][1], (line, rest[0][2]))
        rd(rest[1:])
        return

    if head == "RUN":
        return                                        # operands are catalog names

    # ---- calls -------------------------------------------------------------
    if head == "CALL":
        _analyze_call(rest, line, an, quiet_reads)
        return

    if head in ("EXECUTE", "EXEC", "PERFORM"):
        # CAPTURING/RETURNING are handled above; what is left is TCL redirection:
        #   //SELECT. > list      //OUT. > var      //IN. < x      ,SELECT > list
        # The name left of the arrow is a redirection keyword, not a variable;
        # the name right of a `>` receives the redirected output.
        skip = set()
        i = 0
        while i < len(rest):
            if rest[i][0] == "OP" and rest[i][1] in (">", "<"):
                arrow, j = rest[i][1], i
                while j < len(rest) and rest[j][0] == "OP" and rest[j][1] in (">", "<"):
                    skip.add(j)
                    j += 1
                if j < len(rest):
                    if arrow == ">":
                        an.define(rest[j], line)
                    else:
                        rd(rest[j:j + 1])
                    skip.add(j)
                if i and rest[i - 1][0] == "ID":
                    skip.add(i - 1)                   # SELECT / SELECT. / OUT. / ..
                i = j + 1
                continue
            i += 1
        rd([t for k, t in enumerate(rest) if k not in skip])
        return

    if head == "GET" and rest and _is_op(rest[0], "("):
        # GET(ARG., n) var  -- fetch a command-line argument into var
        j = 0
        depth = 0
        while j < len(rest):
            if _is_op(rest[j], "("):
                depth += 1
            elif _is_op(rest[j], ")"):
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        k = _first_ident(rest[j:])
        if k is not None:
            an.define(rest[j + k], line)
        rd(rest[:j])
        return

    # ---- statements that rewrite an existing variable ----------------------
    if head == "CONVERT":
        j = _find_word(rest, "IN")
        if j is not None and j + 1 < len(rest):
            an.define(rest[j + 1], line)
            rd(rest[:j])
            rd(rest[j + 1:])
        else:
            rd(rest)
        return

    if head == "INS":
        j = _find_word(rest, "BEFORE")
        if j is not None and j + 1 < len(rest):
            an.define(rest[j + 1], line)
            rd(rest[:j])
            rd(rest[j + 2:])
        else:
            rd(rest)
        return

    if head == "REMOVE" and not (rest and _is_op(rest[0], "(")):
        if rest:
            an.define(rest[0], line)
        rd(rest[1:])
        return

    if head == "LOCATE":
        if rest and _is_op(rest[0], "("):
            # LOCATE(elem, dyn, fno; pos) and LOCATE(elem, dyn, fno; pos; "AL")
            semis = _top_level(args := _inside_parens(rest), ";")
            if semis:
                stop = semis[1] if len(semis) > 1 else len(args)
                for part in _split_commas(args[semis[0] + 1:stop]):
                    if len(part) == 1:
                        an.define(part[0], line)
                rd(args[:semis[0]])
            else:
                rd(args)
        else:
            rd(rest)                                  # SETTING form, handled above
        return

    # ---- file handles and select lists -------------------------------------
    if head in TO_DEFINES:
        j = _find_word(rest, "TO")
        if j is not None:
            for part in _split_commas(_upto_stop(rest[j + 1:])):
                if len(part) == 1:
                    an.define(part[0], line)
            rd(rest[:j])
        else:
            rd(rest)
        return

    # ---- reads -------------------------------------------------------------
    if head in READ_LIKE:
        body = rest
        if body and _is_word(body[0], "MAT"):
            body = body[1:]
        targets = _upto_stop(body)
        if head in MULTI_TARGET:
            for part in _split_commas(targets):
                if len(part) == 1:
                    an.define(part[0], line)
        else:
            k = _first_ident(targets)
            if k is not None:
                an.define(targets[k], line)
                rd(targets[:k])
                rd(targets[k + 1:])
            else:
                rd(targets)
        rd(body[len(targets):])
        return

    # ---- everything else led by a keyword is pure expression ---------------
    if head in NON_VARIABLES:
        rd(rest)
        return

    # ---- assignment --------------------------------------------------------
    found = _lhs_assign(toks)
    if found:
        j, op, partial = found
        # An assignment harvested out of an include is not this program's, and
        # its line number points into another file, so it only ever suppresses.
        an.define(toks[0], line, weak=partial and an.strict_init,
                  assign=not quiet_reads)
        if op != "=":
            rd(toks[:1])                              # X += .. reads X as well
        rd(toks[1:j])                                 # subscript expressions
        rd(toks[j + 1:])
        return

    rd(toks)


def _analyze_call(rest, line, an, quiet_reads):
    """CALL target(args).  Pick passes by reference, so a bare-variable argument
    may be an output parameter rather than a read."""
    i = 0
    if i < len(rest) and _is_op(rest[i], "*"):
        i += 1                                        # CALL *OPEN.FILE(..)
    target = None
    if i < len(rest) and rest[i][0] in ("ID", "SYS", "STR"):
        if rest[i][0] == "ID":
            target = rest[i]                          # SYS is `CALL @VAR`, STR a
        i += 1                                        # literal; neither resolves
    # No parenthesised list at all is a call with no arguments, not an unknown
    # one -- `CALL FOO` against a SUBROUTINE that declares parameters is exactly
    # the mismatch worth reporting.
    parts = _split_commas(_inside_parens(rest[i:]))
    if target is not None and not quiet_reads:
        an.calls.append((target[1], len(parts), line, target[2]))
    for part in parts:
        part = [t for t in part if not _is_word(t, "MAT")]
        if len(part) == 1 and part[0][0] == "ID" and not an.strict_call:
            an.define(part[0], line)
        elif not quiet_reads:
            an.read_all(part, line)


# ---------------------------------------------------------------------------
# $INCLUDE / $INSERT
# ---------------------------------------------------------------------------

_INCLUDE_RE = re.compile(
    r"^\s*\$?\s*(?:INCLUDE|INSERT)\s+([A-Za-z0-9._$%#-]+)\s*([A-Za-z0-9._$%#-]+)?",
    re.IGNORECASE)


def parse_include(raw):
    """Return (directory_or_None, name) for an include directive, else None."""
    s = raw.lstrip().upper()
    if not (s.startswith("$") or s.startswith("INCLUDE ") or s.startswith("INCLUDE\t")
            or s.startswith("INSERT ") or s.startswith("INSERT\t")):
        return None
    m = _INCLUDE_RE.match(raw)
    if not m:
        return None
    first, second = m.group(1), m.group(2)
    return (first, second) if second else (None, first)


def resolve_include(spec, search_dirs):
    directory, name = spec
    for base in search_dirs:
        if directory:
            p = os.path.join(base, directory, name)
            if os.path.isfile(p):
                return p
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    for base in search_dirs:                          # last resort: any subdir
        try:
            subs = sorted(os.listdir(base))
        except OSError:
            continue
        for sub in subs:
            p = os.path.join(base, sub, name)
            if os.path.isfile(p):
                return p
    return None


# ---------------------------------------------------------------------------
# callee lookup, for the mismatched-parameter check
# ---------------------------------------------------------------------------

class SubroutineIndex(object):
    """Name -> declared parameter count, for the programs on disk.

    The lookup folds case explicitly rather than leaning on a case-insensitive
    filesystem: the lexer uppercases every identifier, but the files do not all
    match (src/BP/PLK_gen), and the same sweep has to behave the same way when
    it is run somewhere other than Windows.

    Directories are indexed once up front and headers parsed on first use -- a
    tree-wide sweep asks about the same few hundred subroutines tens of
    thousands of times.
    """

    def __init__(self, dirs):
        self.paths = {}
        for base in dirs:
            try:
                with os.scandir(base) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_file():
                        # First directory wins, matching locate_program.
                        self.paths.setdefault(entry.name.upper(), entry.path)
                except OSError:
                    continue
        self.sigs = {}

    def params(self, name):
        """Declared parameter count, or None when the name is not a checkable
        SUBROUTINE -- unresolvable, or resolving to something with no header."""
        if name not in self.sigs:
            path = self.paths.get(name)
            self.sigs[name] = None if path is None else _read_signature(path)
        return self.sigs[name]


def _read_signature(path):
    """Parameter count of a file's SUBROUTINE header, else None.

    UniVerse requires the header to be the first statement, so anything else
    found there -- FUNCTION, PROGRAM, or ordinary code -- means this is not a
    subroutine and nothing can be checked against it.  Compiler directives are
    stepped over; comments and blank lines tokenize to nothing already.
    """
    try:
        lines = read_lines(path)
    except (OSError, ValueError):
        return None
    if is_pick_proc(lines):
        return None
    for raw in lines:
        segs = tokenize(raw)
        if not segs:
            continue
        toks = segs[0]
        if _is_op(toks[0], "$"):
            continue                                  # $OPTIONS, $MAP, ..
        if toks[0][0] == "ID" and toks[0][1] == "SUBROUTINE":
            return len(_split_commas(_inside_parens(toks[1:])))
        return None
    return None


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def read_lines(path):
    # latin-1 rather than utf-8: it round-trips all 256 byte values one-for-one,
    # so a column number here is the same column the editor sees.  utf-8 with
    # replacement collapses multi-byte sequences into a single U+FFFD and shifts
    # every column after it -- 14 files in src/BP carry raw MultiValue mark bytes
    # that would do exactly that.  Pick identifiers are ASCII, so nothing is lost;
    # only comments and string literals could look odd, and both are discarded.
    with open(path, "rb") as fh:
        return fh.read().decode("latin-1").splitlines()


_PQ_RE = re.compile(r"^PQN?(?![A-Za-z0-9._$%])(.*)$", re.IGNORECASE)
_PROC_COMMENT_RE = re.compile(r"^[C*]([ \t].*)?$", re.IGNORECASE)


def is_pick_proc(lines):
    """True for a Pick PROC rather than a Pick BASIC program.

    A PROC opens with the `PQ` / `PQN` marker, optionally preceded by `C` or `*`
    comment lines (`PQ S Saved at 12:55 ..` is also valid).  PROC is a completely
    different language, so such a file is skipped rather than reported on.

    src/PROK is refused before it ever gets here and no file in src/BP is a PROC,
    so this only fires for a PROC named by a path from somewhere else -- a copy in
    a scratch directory, say.  Cheap enough to keep as a backstop.
    """
    seen = 0
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        seen += 1
        if seen > 12:
            return False
        m = _PQ_RE.match(s)
        if m and not m.group(1).lstrip().startswith("="):
            return True
        if not _PROC_COMMENT_RE.match(s):
            return False                    # real BASIC starts here
    return False


def _reachability(marked, lineno, an, reachable, dead_from):
    """Advance the fall-through state across one source line.

    Deliberately one-dimensional: it tracks only whether the statement above
    hands control down, and treats any label or block keyword as proof that
    something else might branch in.  That is sound without a control-flow graph
    -- UniVerse cannot compute a branch target, so a statement with no label
    between it and an unconditional jump is genuinely unreachable -- and it is
    the only shape worth reporting in code this size.
    """
    first = marked[0][1]
    head = first[0][1] if first[0][0] == "ID" else None
    labelled = ((len(first) >= 2 and first[0][0] in ("ID", "NUM")
                 and _is_op(first[1], ":"))
                or first[0][0] == "NUM")

    # An entry point is reached from outside the program, so it ends a dead run
    # the same way a label does.
    if head in ENTRY_POINTS:
        return True, None

    # A declaration is compile-time; it is neither reached nor unreachable.
    if head in DECLARATIONS or _is_op(first[0], "$"):
        return reachable, dead_from

    if not reachable:
        if labelled or head in REJOIN:
            return True, None
        if dead_from is not None:
            # A lone RETURN parked under an unconditional GO is deliberate, not a
            # mistake: it marks where this stretch would exit once someone turns it
            # into a subroutine, and the convention is to leave it in place.  Step
            # over it -- anything further down the run is still reported.
            if dead_from[1] in ("GO", "GOTO") and _is_bare_return(marked):
                return False, dead_from
            an.dead[lineno] = (first[0][2], dead_from[0], dead_from[1])
            # Only the head of each run is reported; the rest says nothing new.
            return False, None
        return False, None

    # A THEN or ELSE makes the REST OF THE LINE conditional, semicolons and all:
    # `MATREAD .. ELSE X=0 ; RETURN` returns only when the read fails, so the
    # line falls through.  Nothing after a boundary word can end the flow, which
    # makes the test simply "no boundary word opened any segment on this line".
    if all(op is None or op == ";" for op, _seg in marked):
        last = marked[-1][1]
        tail = last[0][1] if last[0][0] == "ID" else None
        # `_lhs_assign` guards the handful of terminator words that are also
        # legal variable names -- `ENTER = ..` is real in this tree.
        if tail in TERMINATORS and _lhs_assign(last) is None:
            return False, (lineno, tail)
    return True, dead_from


def scan_file(path, an, search_dirs, quiet_reads, seen):
    real = os.path.realpath(path)
    if real in seen:
        return
    seen.add(real)
    lines = read_lines(path)
    if is_pick_proc(lines):
        an.not_basic = True
        return
    reachable, dead_from = True, None
    for lineno, raw in enumerate(lines, 1):
        spec = parse_include(raw)
        if spec:
            target = resolve_include(spec, search_dirs)
            if target:
                an.resolved_includes.append(target)
                scan_file(target, an, search_dirs, True, seen)
            else:
                an.unresolved_includes.append((lineno, raw.strip()))
            # Spliced-in code may carry the label that was jumped to.
            reachable, dead_from = True, None
            continue
        marked = tokenize_marked(raw)
        if marked and not quiet_reads:
            reachable, dead_from = _reachability(
                marked, lineno, an, reachable, dead_from)
        for index, (_opener, seg) in enumerate(marked):
            analyze(seg, lineno, an, quiet_reads, line_start=(index == 0))


class IgnoreList(object):
    """Names to treat as initialized -- exact names plus `PREFIX*` globs."""

    def __init__(self, patterns):
        self.exact = set()
        self.prefixes = []
        for pat in patterns:
            pat = pat.strip().upper()
            if not pat:
                continue
            if pat.endswith("*"):
                self.prefixes.append(pat[:-1])
            else:
                self.exact.add(pat)

    def __contains__(self, name):
        if name in self.exact:
            return True
        return any(name.startswith(p) for p in self.prefixes)

    def __bool__(self):
        return bool(self.exact or self.prefixes)

    __nonzero__ = __bool__


def collect(path, args, search_dirs, ignore, subs=None):
    """Analyse one program and return (analysis, findings).

    A finding is (line, col, name, code, severity, message).  Both output formats
    render this same list, so the human report and the editor diagnostics can
    never disagree about what was found.
    """
    an = Analysis(strict_call=args.strict_call, strict_init=args.strict_init)
    scan_file(path, an, search_dirs, False, set())
    if an.not_basic:
        return an, None

    known = set(an.defs) | an.labels | an.local_funcs
    if not args.strict_init:
        known |= set(an.weak_defs)

    found = []
    if args.uninitialized:
        for name, (ln, col) in an.reads.items():
            if name not in known and name not in ignore:
                found.append((ln, col, name, "uninit", "warning",
                              "%s is read but never assigned" % name))

    if args.orphan_next:
        for name, (ln, col) in an.next_vars.items():
            if name not in an.for_vars and name not in ignore:
                found.append((ln, col, name, "orphan-next", "warning",
                              "no FOR loop uses control variable %s" % name))

    if args.param_check and subs is not None:
        # When the callee's source is not in the checkout, the program's own
        # other calls to it are the only evidence there is -- and it is good
        # evidence, because UniVerse has no optional parameters: if 29 sites
        # pass seven arguments and one passes none, one of them is wrong, and
        # it is not the twenty-nine.  This is what catches a bare `CALL FOO`
        # against a subroutine that lives only on the server.
        by_name = collections.defaultdict(collections.Counter)
        for name, got, _ln, _col in an.calls:
            by_name[name][got] += 1

        for name, got, ln, col in an.calls:
            if name in ignore:
                continue
            want = subs.params(name)
            if want is not None:
                if want != got:
                    found.append((ln, col, name, "param-mismatch", "error",
                                  "%s expects %d parameter(s), %d passed"
                                  % (name, want, got)))
                continue

            counts = by_name[name]
            if len(counts) < 2:
                continue                      # nothing to disagree with
            usual, seen_usual = counts.most_common(1)[0]
            # Only report against a strict plurality.  Two sites disagreeing
            # one-to-one prove a bug without saying which side is the bug, and
            # naming both would just be noise.
            if got == usual or counts[got] >= seen_usual:
                continue
            found.append((ln, col, name, "param-mismatch", "error",
                          "%s is called with %d argument(s) at %d other site(s)"
                          " in this program, %d passed here (no SUBROUTINE"
                          " header found to confirm against)"
                          % (name, usual, seen_usual, got)))

    if args.deadcode:
        for ln, (col, tline, tkw) in an.dead.items():
            found.append((ln, col, "after %s on line %d" % (tkw, tline),
                          "dead-code", "warning",
                          "unreachable -- %s on line %d always branches away and"
                          " no label follows it" % (tkw, tline)))

    # An unresolved $INCLUDE may hold the DIM, so the check stays silent
    # rather than guess; the unresolved-include finding already says why.
    if args.dimcheck and not an.unresolved_includes:
        seen_mat = set()
        for name, ln, col, kw in an.mat_uses:
            if name in an.dims or name in ignore or name in seen_mat:
                continue
            seen_mat.add(name)
            found.append((ln, col, name, "undimensioned", "error",
                          "%s needs %s, but nothing dimensions it -- DIM,"
                          " COMMON with a subscript, or a MAT parameter"
                          % (name, kw)))

    if args.undefined:
        for key, (ln, col, text) in an.label_ref_sites.items():
            if key not in an.label_all_defs and text not in ignore:
                found.append((ln, col, text, "undefined-label", "error",
                              "branches to %s, which this program never"
                              " defines" % text))

    if args.unreferenced:
        for key, (ln, col, text) in an.label_defs.items():
            if key in MACRO_LABELS:
                continue
            if key not in an.label_refs and text not in ignore:
                found.append((ln, col, text, "unused-label", "info",
                              "label %s is never named by a GOTO, GOSUB or"
                              " RETURN TO" % text))

    if args.strict_init and args.uninitialized:
        for name, (ln, col) in an.weak_defs.items():
            if name not in an.defs and name not in an.labels:
                found.append((ln, col, name, "partial-init", "warning",
                              "%s is only ever written by %s<n>= / %s(n)= / %s +="
                              % (name, name, name, name)))

    if args.unused:
        for name, (ln, col) in an.assigns.items():
            if name in an.reads or name in an.labels or name in ignore:
                continue
            # A name this program also writes some other way is left alone: a
            # parameter, a COMMON member and a CALL argument are all read by
            # somebody else, and a FOR control variable is read by its own loop.
            if (name in an.other_defs or name in an.next_vars
                    or name in an.dims):
                continue
            found.append((ln, col, name, "write-only", "info",
                          "%s is assigned but never read" % name))

    for ln, text in an.unresolved_includes:
        found.append((ln, 1, text, "unresolved-include", "info",
                      "cannot resolve %s -- anything it declares is invisible,"
                      " so findings here may be false positives" % text))

    found.sort(key=lambda f: (f[0], f[1], f[3]))
    return an, found


HEADINGS = (
    ("param-mismatch",
     "MISMATCHED PARAMETERS -- argument count differs from the SUBROUTINE header"),
    ("undefined-label", "UNDEFINED LABEL -- branches to a label that does not exist"),
    ("undimensioned",
     "UNDIMENSIONED MATRIX -- MAT used on a name no DIM ever dimensions"),
    ("dead-code", "DEAD CODE -- control cannot reach this statement"),
    ("uninit", "UNINITIALIZED -- read but never assigned anywhere"),
    ("orphan-next", "ORPHANED NEXT -- no FOR loop uses this control variable"),
    ("unused-label", "UNREFERENCED LABEL -- nothing branches here"),
    ("partial-init", "PARTIAL INIT -- only ever written by VAR<n>= / VAR(n)= / VAR +="),
    ("write-only", "WRITE-ONLY -- assigned but never read"),
)


def report_porcelain(path, findings):
    """One finding per line: PATH:LINE:COL: SEVERITY: CODE: MESSAGE.

    Consumed by the .vscode/tasks.json problemMatcher.  Deliberately flat and
    grep-friendly; nothing is emitted for a clean program.
    """
    return ["%s:%d:%d: %s: %s: %s" % (path, ln, col, severity, code, message)
            for ln, col, _name, code, severity, message in findings]


def report_human(path, an, findings, quiet):
    """Render the grouped report for one program as a list of lines.

    Returning lines rather than printing them is what lets the caller hold every
    program with findings back to the end of the run.
    """
    real = [f for f in findings if f[3] != "unresolved-include"]
    if quiet and not real:
        return []

    out = [path]

    stale = [f for f in findings if f[3] == "unresolved-include"]
    if stale:
        out.append("  WARNING: %d include directive(s) could not be resolved."
                   " Anything" % len(stale))
        out.append("           they declare is invisible here, so findings below"
                   " may be")
        out.append("           false positives.")
        for ln, _c, text, _code, _sev, _msg in stale[:10]:
            out.append("             line %-6d %s" % (ln, text))
        if len(stale) > 10:
            out.append("             ... and %d more" % (len(stale) - 10))
        out.append("           Point --include-path at the missing source"
                   " directory.")
        out.append("")

    if not real:
#        out.append("  CLEAN -- every variable that is read is assigned somewhere.")
        return out

    first = True
    for code, heading in HEADINGS:
        rows = [f for f in real if f[3] == code]
        if not rows:
            continue
        if not first:
            out.append("")
        first = False
        out.append("  %s (%d):" % (heading, len(rows)))
        for ln, col, name, _code, _sev, _msg in rows:
            out.append("    %-42s line %d, col %d" % (name, ln, col))
    return out


def check(path, args, search_dirs, ignore, subs=None):
    an, findings = collect(path, args, search_dirs, ignore, subs)

    if findings is None:                      # a Pick PROC
        lines = []
        if args.format == "human" and not args.quiet:
            lines = [path,
                     "  SKIPPED -- this is a Pick PROC, not a Pick BASIC program."]
        return None, lines

    if args.format == "porcelain":
        lines = report_porcelain(path, findings)
    else:
        lines = report_human(path, an, findings, args.quiet)

    return len([f for f in findings if f[3] != "unresolved-include"]), lines


_WILDCARD = re.compile(r"[*?]")

# Bare names and bare wildcards resolve against the current directory first and
# src/BP second, so the linter works both from inside the repo and on a scratch
# directory of programs pulled off the server with pull-from-master.ps1.
CODE_DIR = "BP"

# Within the repo, these src/ subdirectories are refused rather than scanned:
# src/PROK is Pick PROC, src/TEMPLATES is binary W4 form definitions, and
# src/MENU-ITEMS and src/DICT hold menu and dictionary records.  None is Pick
# BASIC, so feeding any of them to this parser produces pure noise.
EXCLUDED_DIRS = ("PROK", "MENU-ITEMS", "DICT", "TEMPLATES")

# Extensions a wildcard never picks up, so that `lintbasic "*"` in a repo root or
# a mixed scratch directory does not report nonsense about README.md or a .ps1.
# Naming such a file explicitly still lints it -- this applies only to wildcard
# expansion.
#
# The match is CASE-SENSITIVE and deliberately so.  Pick record names are
# uppercase and full of dots, so `splitext` reads a trailing name part as an
# extension: LG.PURGE.LOG, LG.FIX.ZIP, ZUK.CONVERT.XLS and LG.CARRIER.CSV are
# all real programs in src/BP that a case-insensitive match would silently skip.
# Editor and OS clutter is lowercase, which is what makes the distinction work.
NON_SOURCE_EXTS = frozenset("""
.bat .cmd .code-workspace .csv .dll .exe .gif .gz .ico .jpeg .jpg .json .log .md
.o .pdf .png .ps1 .py .pyc .sh .tar .txt .vsix .xls .xlsx .xml .yaml .yml .zip
""".split())


def looks_like_source(path):
    """False for a wildcard match that obviously is not Pick BASIC."""
    base = os.path.basename(path)
    if base.startswith("."):
        return False                     # .env, .gitignore, ..
    return os.path.splitext(base)[1] not in NON_SOURCE_EXTS


def excluded_dir(path, src):
    """Name of the off-limits src/ subdirectory `path` sits in, else None."""
    try:
        full = os.path.realpath(path)
    except OSError:
        return None
    for name in EXCLUDED_DIRS:
        root = os.path.realpath(os.path.join(src, name))
        if full == root or full.startswith(root + os.sep):
            return name
    return None


def locate_program(name, src):
    """Current directory first, then src/BP."""
    if os.path.isfile(name):
        return name
    p = os.path.join(src, CODE_DIR, name)
    return p if os.path.isfile(p) else None


def expand_program(name, src):
    """Return (files, blocked) for one command-line argument.

    Without a wildcard this is the ordinary exact lookup.  With `*` or `?` the
    argument is globbed: against the filesystem when it looks like a path, and
    otherwise against the current directory, falling back to src/BP when the
    current directory holds no match -- so a bare pattern still resolves from
    anywhere in the repo.  Matches inside an EXCLUDED_DIRS directory are dropped;
    `blocked` names the ones that were, so the caller can say why an argument
    came back empty.
    """
    def select(matches, drop_non_source):
        files, blocked = [], set()
        for path in sorted(matches):
            if not os.path.isfile(path):
                continue
            if drop_non_source and not looks_like_source(path):
                continue
            off_limits = excluded_dir(path, src)
            if off_limits:
                blocked.add(off_limits)
            else:
                files.append(path)
        return files, blocked

    if not _WILDCARD.search(name):
        path = locate_program(name, src)
        return select([path] if path else [], False)

    if os.path.isabs(name) or "/" in name or "\\" in name:
        return select(glob.glob(name), True)

    files, blocked = select(glob.glob(name), True)           # current directory
    if not files and not blocked:
        # Nothing usable here -- fall back to src/BP so a bare pattern still
        # resolves from anywhere in the repo.  The `blocked` guard matters: if the
        # current directory IS src/PROK the caller must hear about that rather
        # than have the whole of src/BP quietly linted instead.
        files, blocked = select(glob.glob(os.path.join(src, CODE_DIR, name)), True)
    return files, blocked


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Report Pick BASIC variables that are read but never assigned,"
                    " and labels that nothing branches to.")
    ap.add_argument("programs", nargs="+",
                    help="program names, paths, or * / ? wildcards;"
                         " comma-separated lists accepted. Bare names and bare"
                         " wildcards resolve against the current directory first,"
                         " then src/BP; a pattern containing a slash is globbed as"
                         " given. Quote the pattern so the shell does not expand it"
                         " first. Wildcards skip dotfiles and non-BASIC extensions;"
                         " src/PROK, src/MENU-ITEMS, src/DICT and src/TEMPLATES are"
                         " refused")
    ap.add_argument("--src", default=None,
                    help="repository src/ directory (default: auto-detected)")
    ap.add_argument("--include-path", action="append", default=[], metavar="DIR",
                    help="extra directory to search for $INCLUDE targets (repeatable)")
    ap.add_argument("--no-param-check", action="store_false", dest="param_check",
                    help="skip the mismatched-parameter findings; this is the one"
                         " off switch that also saves time, since the callee"
                         " index and headers are then never read")
    ap.add_argument("--no-uninitialized", action="store_false",
                    dest="uninitialized",
                    help="skip the uninitialized-variable findings, and the"
                         " partial-init findings --strict-init adds to them;"
                         " leaves the other checks running")
    ap.add_argument("--no-orphan-next", action="store_false",
                    dest="orphan_next",
                    help="skip the orphaned-NEXT findings; leaves the other"
                         " checks running")
    ap.add_argument("--no-deadcode", action="store_false", dest="deadcode",
                    help="skip the unreachable-code findings; leaves the other"
                         " checks running")
    ap.add_argument("--no-dimcheck", action="store_false", dest="dimcheck",
                    help="skip the undimensioned-matrix findings; leaves the"
                         " other checks running")
    ap.add_argument("--no-undefined", action="store_false", dest="undefined",
                    help="skip the undefined-label findings; leaves the other"
                         " checks running")
    ap.add_argument("--no-unreferenced", action="store_false",
                    dest="unreferenced",
                    help="skip the unreferenced-label findings; leaves the"
                         " other checks running")
    ap.add_argument("--no-unused-var", action="store_false", dest="unused",
                    help="skip the write-only-variable findings; leaves the"
                         " other checks running")
    ap.add_argument("--strict-init", action="store_true",
                    help="treat VAR<n>=, VAR(n)= and VAR += as NOT initializing VAR,"
                         " and report names only ever written that way")
    ap.add_argument("--strict-call", action="store_true",
                    help="do not treat CALL arguments as initialized; noisier, but"
                         " catches typos in output-parameter names")
    ap.add_argument("--ignore", action="append", default=[], metavar="NAMES",
                    help="comma-separated names to treat as initialized, with a"
                         " trailing * allowed as a prefix wildcard; useful for"
                         " equates that live in an include this checkout lacks,"
                         " e.g. --ignore 'GE*,UDO_*' (repeatable)")
    ap.add_argument("--format", choices=("human", "porcelain"), default="human",
                    help="human (default) prints the grouped report; porcelain"
                         " prints one finding per line as"
                         " PATH:LINE:COL: SEVERITY: CODE: MESSAGE, for editors and"
                         " grep")
    ap.add_argument("--exit-zero", action="store_true",
                    help="always exit 0, even when findings were reported; use this"
                         " from an editor task, where the findings travel through"
                         " the problem matcher and a non-zero exit only looks like"
                         " a crash")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="print nothing for programs with no findings")
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    src = args.src or os.path.join(os.path.dirname(here), "src")
    if not os.path.isdir(src):
        src = os.path.join(os.getcwd(), "src")
    search_dirs = [os.path.abspath(d) for d in args.include_path] + [src]

    names = []
    for chunk in args.programs:
        names.extend(n.strip() for n in chunk.split(",") if n.strip())

    patterns = []
    for chunk in args.ignore:
        patterns.extend(chunk.split(","))
    ignore = IgnoreList(patterns)

    # One index for the whole run: every callee header is read at most once, no
    # matter how many programs call it.
    subs = SubroutineIndex([os.getcwd(), os.path.join(src, CODE_DIR)]) \
        if args.param_check else None

    # Expand everything up front so overlapping patterns (`W4SUB*,W4SUBORD*`)
    # check each file once.
    targets, seen, missing = [], set(), 0
    for name in names:
        found, blocked = expand_program(name, src)
        if not found:
            if blocked:
                sys.stderr.write(
                    "refused: %s is in src/%s, which this checker does not scan"
                    " (only src/%s holds Pick BASIC)\n"
                    % (name, "/src/".join(sorted(blocked)), CODE_DIR))
            elif _WILDCARD.search(name):
                where = name if ("/" in name or "\\" in name) \
                    else "%s and %s" % (os.getcwd(), os.path.join(src, CODE_DIR))
                sys.stderr.write("no files matched: %s (searched %s)\n" % (name, where))
            else:
                sys.stderr.write("not found: %s (searched %s and %s)\n"
                                 % (name, os.getcwd(),
                                    os.path.join(src, CODE_DIR)))
            missing += 1
            continue
        for path in found:
            key = os.path.realpath(path)
            if key not in seen:
                seen.add(key)
                targets.append(path)

    # Programs with findings are held back and printed last, so that after a
    # wildcard sweep the interesting output is sitting just above the prompt
    # instead of scrolled off the top.  Alphabetical order is preserved inside
    # each group.
    total, checked, skipped = 0, 0, 0
    quiet_lines, issue_lines = [], []
    clean_count, with_issues = 0, 0
    for path in targets:
        result, lines = check(path, args, search_dirs, ignore, subs)
        if result is None:
            skipped += 1
            quiet_lines.extend(lines)
            continue
        checked += 1
        total += result
        if result:
            with_issues += 1
            if issue_lines:
                issue_lines.append("")      # blank line between programs
            issue_lines.extend(lines)
        else:
            clean_count += 1
            quiet_lines.extend(lines)

    # Section headers only earn their four lines when there is more than one
    # program to divide up, and porcelain must stay one finding per line.
    banner = "=" * 70
    headers = len(targets) > 1 and args.format == "human"

    def section(label):
        print(banner)
        print(label)
        print(banner)

    if quiet_lines:
        if headers:
            if clean_count and skipped:
                section("%d program(s) with no findings, %d skipped"
                        % (clean_count, skipped))
            elif clean_count:
                section("%d program(s) with no findings" % clean_count)
            else:
                section("%d file(s) skipped" % skipped)
        for line in quiet_lines:
            print(line)

    if issue_lines:
        if headers:
            if quiet_lines:
                print("")
            section("%d program(s) with findings" % with_issues)
        for line in issue_lines:
            print(line)

    # porcelain output must stay one-finding-per-line for the problem matcher, so
    # no summary is printed there.
    tail = " (%d skipped)" % skipped if skipped else ""
    if args.format == "porcelain":
        pass
    elif total:
        print("%d finding(s) across %d program(s)%s." % (total, checked, tail))
    elif checked:
        ran = []
        if args.param_check:
            ran.append("mismatched parameters")
        if args.uninitialized:
            ran.append("uninitialized variables")
        if args.orphan_next:
            ran.append("orphaned NEXTs")
        if args.deadcode:
            ran.append("dead code")
        if args.dimcheck:
            ran.append("undimensioned matrices")
        if args.undefined:
            ran.append("undefined labels")
        if args.unreferenced:
            ran.append("unreferenced labels")
        if not ran:
            what = "findings"
        elif len(ran) == 1:
            what = ran[0]
        else:
            what = "%s or %s" % (", ".join(ran[:-1]), ran[-1])
        print("All %d program(s) clean -- no %s%s." % (checked, what, tail))
    elif skipped:
        print("Nothing to check -- %d file(s) skipped." % skipped)
    if args.exit_zero:
        return 0
    if missing:
        return 2
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
