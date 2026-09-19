# Protocols for the tests that remain

The reference run (`mplpb-net experiment`) is a mechanical rehearsal. Its
corpora, queries, and code share one author, so it can show the implementation
does what the paper says, and nothing more. The two protocols below are the
tests that can falsify the architecture. Neither has been run.

---

## 1. Blind stranger recovery (falsifiers F1 and F11)

### Participants

People who have never seen this project, its author, its repository, or anyone
briefed by its author. Record, for each participant, only: whether they have
used a command line; whether they can compute a SHA-256 hash with a tool they
already have. Aim for at least twelve, so that a failure rate is more than an
anecdote.

Exclude anyone who has read the paper, the README, or any MPLPB document.
Recovery by the author, or by anyone told what to look for, does not test F1.

### Materials

Prepare, before recruitment:

- Three descendant corpora grown from the reference seed, in different
  domains, each with at least one supersession and one machine-derived page.
- One ZIP per participant containing exactly one of those corpora and nothing
  else. No README from the repository, no software, no node directory.
- The ten questions below, printed.
- An answer key for each corpus, written and sealed before recruitment.

### Task

Give the participant the ZIP, the questions, a computer with a browser and a
file manager, and two hours. They may use any tool already on the computer and
any web search, but may not contact anyone. Ask them to write answers and to
note where they found each one.

1. What is this collection, in one sentence?
2. What topics does it claim to cover? What does it say it does not cover?
3. Which pages are current, and which are old versions?
4. Pick the page with an old version. What changed, and why, according to the collection?
5. Where did this collection come from? Is it an original or a copy of something?
6. Is this copy intact? How do you know?
7. Which pages were written by a machine rather than a person? How far removed from a person?
8. Add one page on a topic the collection covers, so that the collection would still pass its own rules.
9. Make a copy of the collection that is a new collection rather than the same one. What did you have to change?
10. According to the collection's own rules, is your result from question 9 valid? How did you check?

### Grading

A grader who does not know which participant received which corpus scores each
answer against the sealed key as *recovered*, *partial*, or *not recovered*.
Questions 8 to 10 are also checked mechanically with `mplpb-net validate`.

Report, per participant and per question: the grade, where they found the
answer, and time taken. Report R as the mean fraction recovered. Report every
question that fewer than half the participants recovered, with what they tried.

**F1 holds** if a reasonable reviewer, shown these results, would say a
stranger cannot recover the corpus without the author.

### Second arm: the prose rules (F11)

Give a separate group of programmers only `spec/validation.html` from the seed,
and ten corpora, three of which are broken in ways the sealed key records.
Ask each to implement the checks in any language and report which corpora pass
and which fail, with reasons. Compare with `mplpb-net validate`.

**F11 holds** if independent implementations built from the prose disagree
with the reference validator on the broken corpora at a material rate.

---

## 2. Ablation: declared scope against flat retrieval (F3, F4)

### Corpora

At least five descendant corpora, including at least two pairs with genuinely
overlapping scope (a corpus and its fork; two independently written corpora on
neighbouring topics).

### Queries

At least one hundred, written by people who have not read any corpus's
declared scope, only a one-line description of each domain. Include, in
roughly equal numbers:

- questions one corpus clearly owns;
- questions in a domain's words that the scope does not use (vocabulary mismatch);
- questions on the overlap between two corpora (true collisions);
- questions that partly overlap but have one distinguishing term;
- questions no corpus covers.

Label each with its correct outcome before any system is run, by two labellers
who then reconcile. Report their initial agreement.

### Conditions

- **(a) Declared scope.** `mplpb-net route` / `ask` as specified.
- **(b) Flat retrieval.** BM25 over every page of every corpus, no scope
  information, return the top page.
- **(c) Flat with a collision rule.** As (b), but return *ambiguous* when the
  top two pages come from different corpora within a score margin tuned on a
  held-out tenth of the queries.

### Measures

Routing accuracy on owned questions; ambiguity preservation on true collisions;
the rate at which each condition returns a page from the wrong corpus; the
rate at which each returns anything at all for uncovered questions.

**F3 holds** if (b) or (c) matches (a) on routing accuracy and wrong-corpus
rate. **F4 holds** if (a) routes true collisions to a single corpus at a
material rate.

---

## 3. What to publish

Whatever the result. A protocol that is only reported when it succeeds is not
a test. Publish the corpora, the queries, the sealed keys, the grades, and the
participants' own words on the questions they could not answer.
