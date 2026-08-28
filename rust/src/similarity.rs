//! difflib.SequenceMatcher, ported at the algorithm level. The gate's fuzzy
//! baseline matching depends on its exact ratio semantics. That includes
//! autojunk: in sequences of 200+ elements, an element occupying more than
//! 1% cannot seed a match but may extend one.

use std::collections::HashMap;

pub struct SequenceMatcher {
    a: Vec<char>,
    b: Vec<char>,
    b2j: HashMap<char, Vec<usize>>,
}

impl SequenceMatcher {
    pub fn new(a: &str, b: &str) -> Self {
        let a: Vec<char> = a.chars().collect();
        let b: Vec<char> = b.chars().collect();
        let mut b2j: HashMap<char, Vec<usize>> = HashMap::new();
        for (i, ch) in b.iter().enumerate() {
            b2j.entry(*ch).or_default().push(i);
        }
        let n = b.len();
        if n >= 200 {
            let ntest = n / 100 + 1;
            b2j.retain(|_, idxs| idxs.len() <= ntest);
        }
        SequenceMatcher { a, b, b2j }
    }

    fn find_longest_match(&self, alo: usize, ahi: usize, blo: usize, bhi: usize) -> (usize, usize, usize) {
        let (mut besti, mut bestj, mut bestsize) = (alo, blo, 0usize);
        let mut j2len: HashMap<usize, usize> = HashMap::new();
        for i in alo..ahi {
            let mut newj2len: HashMap<usize, usize> = HashMap::new();
            if let Some(indices) = self.b2j.get(&self.a[i]) {
                for &j in indices {
                    if j < blo {
                        continue;
                    }
                    if j >= bhi {
                        break;
                    }
                    let k = if j > 0 { j2len.get(&(j - 1)).copied().unwrap_or(0) + 1 } else { 1 };
                    newj2len.insert(j, k);
                    if k > bestsize {
                        (besti, bestj, bestsize) = (i + 1 - k, j + 1 - k, k);
                    }
                }
            }
            j2len = newj2len;
        }
        while besti > alo && bestj > blo && self.a[besti - 1] == self.b[bestj - 1] {
            (besti, bestj, bestsize) = (besti - 1, bestj - 1, bestsize + 1);
        }
        while besti + bestsize < ahi && bestj + bestsize < bhi && self.a[besti + bestsize] == self.b[bestj + bestsize]
        {
            bestsize += 1;
        }
        (besti, bestj, bestsize)
    }

    fn matching_size(&self) -> usize {
        // the get_matching_blocks queue walk, keeping only the total size
        let mut total = 0;
        let mut queue = vec![(0, self.a.len(), 0, self.b.len())];
        while let Some((alo, ahi, blo, bhi)) = queue.pop() {
            let (i, j, k) = self.find_longest_match(alo, ahi, blo, bhi);
            if k > 0 {
                total += k;
                if alo < i && blo < j {
                    queue.push((alo, i, blo, j));
                }
                if i + k < ahi && j + k < bhi {
                    queue.push((i + k, ahi, j + k, bhi));
                }
            }
        }
        total
    }

    pub fn ratio(&self) -> f64 {
        let t = self.a.len() + self.b.len();
        if t == 0 {
            return 1.0;
        }
        2.0 * self.matching_size() as f64 / t as f64
    }

    pub fn quick_ratio(&self) -> f64 {
        let t = self.a.len() + self.b.len();
        if t == 0 {
            return 1.0;
        }
        let mut fullbcount: HashMap<char, i64> = HashMap::new();
        for ch in &self.b {
            *fullbcount.entry(*ch).or_insert(0) += 1;
        }
        let mut avail: HashMap<char, i64> = HashMap::new();
        let mut matches = 0i64;
        for ch in &self.a {
            let numb = *avail
                .entry(*ch)
                .or_insert_with(|| fullbcount.get(ch).copied().unwrap_or(0));
            avail.insert(*ch, numb - 1);
            if numb > 0 {
                matches += 1;
            }
        }
        2.0 * matches as f64 / t as f64
    }

    pub fn real_quick_ratio(&self) -> f64 {
        let (la, lb) = (self.a.len(), self.b.len());
        if la + lb == 0 {
            return 1.0;
        }
        2.0 * la.min(lb) as f64 / (la + lb) as f64
    }
}
