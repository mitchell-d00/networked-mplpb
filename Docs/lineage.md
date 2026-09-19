# Lineage

Four sources fold into this package: the Networked MPLPB paper's first draft,
the Smart Local front end, the Local Mirror back end, and a review of the
first draft. This note records what was carried over unchanged, what changed
and why, and what was left out, so that places where the implementation
departs from the paper are stated by the author rather than discovered by a
reader.

---

## 1. The first draft of *Networked MPLPB*

**Carried over unchanged.** The seed as S = (A, I, R, P, V, B). Nodes as
(ID, S, D) with discovery descriptions answering seven questions. Hubs as
corpora of corpus descriptions. Routing by declared scope, never merging
ambiguous scopes. Provenance envelopes, and the line that a remote answer
without remote provenance is a local hallucination with better transportation.
Origin depth. Offline as a state, not a failure. Sneakernet as transport. The
death test and the 2010 computer test. Conditions A to H and their metrics.
The failure modes and falsifiers.

**Changed: provenance is verified, not carried.** The draft required that the
envelope travel; nothing stopped a relay rewriting it. Now every page reduces
to an Ed25519 signature over a fingerprint over a page hash
(`retrieve.py`, `node.py`, `ed25519.py`).

**Changed: scope has a vocabulary.** The draft left open whether scopes were
free text. They are now a sentence plus scope terms drawn from a vocabulary the
seed carries and descendants inherit (`corpus.py`, `router.py`).

**Changed: supersession is scoped.** The draft's d1 → d2 is now "within corpus
C". A corpus cannot supersede another's documents; it records `diverges-from`
(`validate.py` check N.6).

**Changed: origin-depth rules are explicit.** max + 1 across several sources;
unknown remote sources assumed depth 1; verbatim copying does not reset depth;
ratification resets it and must record who and when (check N.7).

**Changed: validation rules are in the seed.** The draft's 2010 computer test
leaned on Python. Every seed now carries `spec/validation.html`, generated from
the table the code enforces, and a test keeps them in step.

**Changed: node identity.** Unspecified in the draft. It is now derived from a
public key, so an identity collision is a detectable forgery (FM-N14).

**Added.** Four replication relations in place of an undifferentiated "copy".
Hash-chained lineage. Twelve configuration keys. The scale probe. Failure modes
FM-N16 (corpus-ID claim) and FM-N17 (vocabulary drift), and falsifier F11.

**Left out.** Any reputation or ranking of nodes: it would make hubs
authorities. Any network-wide query flooding: routing asks known descriptions
only.

## 2. Smart Local MPLPB (the front end)

**Carried over unchanged:** the page format (`mplpb:*` meta fields, the
`updated` format, the record card, `rel="index"`/`rel="up"`), the
`_log/superseded/` convention, the `<!-- mplpb:entries -->` insertion marker,
the eight local checks 11.1 to 11.8, the rule that routing decides where and
never what, the toggle policy that every configuration key changes observable
behaviour, the layout of the repository, the dual licence, and the voice of
the README.

**Verified in both directions:** a seed built here passes the front end's own
`mplpb validate` and answers its `mplpb ask`.

**Changed:** the parser also skips `nav` and the eyebrow line when extracting
page text, so navigation words do not rank pages. The page model gains the
origin fields; none of the local fields changes meaning.

## 3. The Local Mirror (the back end)

**Carried over:** the site as a directory of plain HTML that works from
`file://`, the card-catalog stylesheet (copied verbatim into every seed), and
the append-only revision log.

## 4. The review

Seven suggestions, all adopted: controlled vocabulary for scope; content
addressing and signatures, with the standard-library tension named; scoped
supersession; origin-depth edge rules; positioning against LOCKSS, OAIS, Git,
Kiwix, IPFS, Secure Scuttlebutt, webrings and directories; blind participants
and graded collisions in the experiment; validation rules stated in prose.
The first four are code, the fifth is Section 2 of the paper, the sixth is
`Docs/PROTOCOL.md` and the experiment's query set, and the seventh is
`spec/validation.html`.
