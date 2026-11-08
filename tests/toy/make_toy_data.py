# File: tests/toy/make_toy_data.py
# Version: 0.1.0
# Last modified: 2026-11-08 (Track B)
# Change: Initial simulator for strandedness smoke tests.
"""Simulate a tiny genome, annotation and paired-end reads with KNOWN strandedness.

Used to check that the local strandedness tools are installed correctly and
that our parser maps their output to the right orientation, before any public
data is downloaded. Everything is synthetic, so the ground truth is exact.

Outputs (in --out):
  genome.fa, annotation.gtf, transcripts.fa
  {FR,RF,UN}_R1.fq.gz / _R2.fq.gz

Orientation conventions (same as RSeQC / how_are_we_stranded_here):
  FR (fr-secondstrand): read 1 is on the transcript's strand  -> RSeQC "1++,1--,2+-,2-+"
  RF (fr-firststrand, dUTP): read 1 is antisense               -> RSeQC "1+-,1-+,2++,2--"
  UN (unstranded): each fragment picks one of the above at random

Usage: python tests/toy/make_toy_data.py --out tests/toy/out
"""
import argparse
import gzip
import os
import random

COMP = str.maketrans("ACGT", "TGCA")


def revcomp(s):
    return s.translate(COMP)[::-1]


def build_genome(rng, n_genes=12, chrom="chrT"):
    """Return genome sequence and a list of 2-exon genes on alternating strands."""
    genes, pos = [], 2000
    for i in range(n_genes):
        e1 = rng.randint(600, 1200)
        intron = rng.randint(300, 800)
        e2 = rng.randint(600, 1200)
        start = pos
        exons = [(start, start + e1), (start + e1 + intron, start + e1 + intron + e2)]
        genes.append({"id": f"TG{i + 1:03d}", "strand": "+" if i % 2 == 0 else "-", "exons": exons})
        pos = exons[-1][1] + rng.randint(1500, 3000)
    seq = "".join(rng.choice("ACGT") for _ in range(pos + 2000))
    return chrom, seq, genes


def transcript_seq(genome, gene):
    s = "".join(genome[a:b] for a, b in gene["exons"])
    return s if gene["strand"] == "+" else revcomp(s)


def write_reference(out, chrom, genome, genes):
    with open(os.path.join(out, "genome.fa"), "w") as f:
        f.write(f">{chrom}\n")
        for i in range(0, len(genome), 60):
            f.write(genome[i:i + 60] + "\n")
    with open(os.path.join(out, "annotation.gtf"), "w") as gtf, \
            open(os.path.join(out, "transcripts.fa"), "w") as fa:
        for g in genes:
            gid, tid, st = g["id"], g["id"] + "-T1", g["strand"]
            lo, hi = g["exons"][0][0], g["exons"][-1][1]
            attr = f'gene_id "{gid}"; gene_name "{gid}"; gene_biotype "protein_coding";'
            tattr = attr + f' transcript_id "{tid}"; transcript_name "{tid}"; transcript_biotype "protein_coding";'
            # GTF is 1-based, inclusive
            gtf.write(f"{chrom}\ttoy\tgene\t{lo + 1}\t{hi}\t.\t{st}\t.\t{attr}\n")
            gtf.write(f"{chrom}\ttoy\ttranscript\t{lo + 1}\t{hi}\t.\t{st}\t.\t{tattr}\n")
            for n, (a, b) in enumerate(g["exons"], 1):
                gtf.write(f'{chrom}\ttoy\texon\t{a + 1}\t{b}\t.\t{st}\t.\t{tattr} exon_number "{n}";\n')
            # Description after the ID is required: how_are_we_stranded_here splits
            # headers on a space, so a bare ">ID" keeps the newline and fails to match.
            fa.write(f">{tid} gene:{gid}\n{transcript_seq(genome, g)}\n")


def mutate(rng, s, rate=0.005):
    return "".join(rng.choice("ACGT".replace(c, "")) if rng.random() < rate else c for c in s)


def simulate(rng, out, txs, mode, n_pairs, read_len=100):
    q = "I" * read_len
    with gzip.open(os.path.join(out, f"{mode}_R1.fq.gz"), "wt") as r1, \
            gzip.open(os.path.join(out, f"{mode}_R2.fq.gz"), "wt") as r2:
        for i in range(n_pairs):
            t = rng.choice(txs)
            flen = max(read_len + 20, int(rng.gauss(250, 30)))
            st = rng.randint(0, len(t) - flen)
            frag = t[st:st + flen]
            sense, anti = frag[:read_len], revcomp(frag)[:read_len]
            m = mode if mode != "UN" else rng.choice(["FR", "RF"])
            a, b = (sense, anti) if m == "FR" else (anti, sense)
            name = f"@toy{mode}_{i}"
            r1.write(f"{name}/1\n{mutate(rng, a)}\n+\n{q}\n")
            r2.write(f"{name}/2\n{mutate(rng, b)}\n+\n{q}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/toy/out")
    ap.add_argument("--pairs", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=535)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)
    chrom, genome, genes = build_genome(rng)
    write_reference(args.out, chrom, genome, genes)
    txs = [transcript_seq(genome, g) for g in genes]
    for mode in ("FR", "RF", "UN"):
        simulate(rng, args.out, txs, mode, args.pairs)
    print(f"Wrote toy data for {len(genes)} genes and {args.pairs} pairs per mode to {args.out}")


if __name__ == "__main__":
    main()
