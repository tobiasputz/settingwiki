from __future__ import annotations

"""Small, dependency-free semantic search for Seeker.

This deliberately avoids a hosted embedding API and heavyweight transformer runtime.
It builds a compact distributional index from the spoiler-filtered Codex itself:
BM25 lexical scoring + concept expansion + corpus co-occurrence neighbours.  The
co-occurrence layer lets setting-specific vocabulary become semantically related
from the way the GM actually writes it, while keeping memory predictable on Railway.
"""

from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
import hashlib
import math
import re
import unicodedata
from typing import Iterable

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'’-]{1,40}")
_STOP = {
    'the','and','for','that','with','this','from','are','was','were','have','has','had','not','but','into','its','their','they','them','then','than','who','what','when','where','which','while','about','also','only','over','under','after','before','between','through','during','can','could','would','should','will','may','might','there','here','his','her','hers','him','our','your','you','she','he','it','a','an','of','to','in','on','at','by','as','is','be','or','if','so','no','do','does','did','been','being','these','those','such','very','more','most','some','any','all','one','two','new','old'
}

# Generic concepts make natural-language player queries useful even before the
# setting corpus has enough repetition to learn a relationship itself.
_CONCEPT_GROUPS = [
    {'king','queen','ruler','monarch','sovereign','emperor','empress','royal','crown','throne'},
    {'city','town','village','settlement','capital','metropolis','hamlet'},
    {'country','nation','kingdom','empire','realm','state','territory'},
    {'god','goddess','deity','divine','religion','faith','church','temple','cult'},
    {'magic','arcane','spell','sorcery','wizard','mage','ritual','enchantment'},
    {'war','battle','conflict','army','military','soldier','siege','invasion'},
    {'dead','death','undead','ghost','spirit','grave','cemetery','necromancy'},
    {'forest','woods','jungle','grove','wilderness'},
    {'sea','ocean','river','lake','water','coast','port','harbor'},
    {'mountain','hill','peak','cliff','range'},
    {'secret','hidden','mystery','unknown','conspiracy','rumor','rumour'},
    {'friend','ally','alliance','trust','companion'},
    {'enemy','rival','foe','hostile','betrayal','betray'},
    {'family','parent','mother','father','child','sibling','brother','sister','lineage','dynasty'},
    {'place','location','region','area','land','site'},
    {'person','people','character','npc','individual','figure'},
    {'organization','organisation','faction','guild','order','group','society'},
    {'history','past','ancient','age','era','origin','founded','founding'},
    {'travel','journey','road','route','distance','path'},
    {'monster','creature','beast','demon','devil','dragon','aberration'},
]
_CONCEPTS: dict[str, set[str]] = {}
for _group in _CONCEPT_GROUPS:
    for _term in _group:
        _CONCEPTS[_term] = _group - {_term}


def _ascii(text: str) -> str:
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode('ascii').lower()
    return text.replace('’', "'")


def _stem(token: str) -> str:
    # Conservative stemming keeps fantasy proper nouns stable while collapsing
    # common English inflections used in natural-language questions.
    if len(token) > 5 and token.endswith('ies'):
        return token[:-3] + 'y'
    if len(token) > 6 and token.endswith('ing'):
        return token[:-3]
    if len(token) > 5 and token.endswith('ed'):
        return token[:-2]
    if len(token) > 5 and token.endswith('es'):
        return token[:-2]
    if len(token) > 4 and token.endswith('s') and not token.endswith('ss'):
        return token[:-1]
    return token


def tokens(text: str) -> list[str]:
    out=[]
    for raw in _TOKEN_RE.findall(_ascii(text)):
        t=_stem(raw.strip("'-"))
        if len(t) < 2 or t in _STOP:
            continue
        out.append(t)
    return out


@dataclass
class Doc:
    slug: str
    title: str
    chapter: str
    excerpt: str
    tf: Counter
    length: int
    title_tokens: set[str]


class SemanticIndex:
    def __init__(self, pages: Iterable[dict]):
        self.docs: list[Doc] = []
        self.df: Counter = Counter()
        self.cooc: dict[str, Counter] = defaultdict(Counter)
        for p in pages:
            title=str(p.get('title') or '')
            chapter=str(p.get('chapter') or 'Setting')
            visibility=(p.get('presentation') or {}).get('visibility','public')
            # Defence in depth: callers already pass a spoiler-filtered wiki, but
            # never index an explicitly hidden presentation even if one slips in.
            if visibility == 'hidden':
                continue
            body=str(p.get('excerpt') or '') if visibility == 'teaser' else str(p.get('plain_text') or p.get('excerpt') or '')
            title_t=tokens(title)
            chapter_t=tokens(chapter)
            body_t=tokens(body[:50000])
            # Title/chapter repetition acts as field weighting without storing a
            # second matrix.
            weighted=body_t + title_t*4 + chapter_t*2
            tf=Counter(weighted)
            doc=Doc(str(p.get('slug') or ''),title,chapter,str(p.get('excerpt') or '')[:500],tf,max(1,len(weighted)),set(title_t))
            self.docs.append(doc)
            uniques=set(tf)
            self.df.update(uniques)
            # Learn local semantics from the strongest terms in each entry.
            salient=[t for t,_ in tf.most_common(36) if len(t)>2]
            for i,a in enumerate(salient):
                for b in salient[i+1:]:
                    self.cooc[a][b]+=1; self.cooc[b][a]+=1
        self.n=max(1,len(self.docs)); self.avgdl=sum(d.length for d in self.docs)/self.n

    def _related(self, term: str, limit: int=5) -> list[tuple[str,float]]:
        cand=self.cooc.get(term)
        if not cand:return []
        da=max(1,self.df.get(term,1)); scored=[]
        for other,c in cand.items():
            db=max(1,self.df.get(other,1))
            # Ochiai/cosine on document-level co-occurrence counts.
            sim=c/math.sqrt(da*db)
            if sim >= .14:
                scored.append((other,sim))
        scored.sort(key=lambda x:(-x[1],x[0]))
        return scored[:limit]

    def search(self, query: str, limit: int=12) -> list[dict]:
        qraw=_ascii(query).strip(); qt=tokens(qraw)
        if not qt:return []
        weights: dict[str,float] = {}
        for term in qt:
            weights[term]=max(weights.get(term,0),1.0)
            for syn in _CONCEPTS.get(term,set()):
                s=_stem(syn);weights[s]=max(weights.get(s,0),.34)
            for rel,sim in self._related(term):
                weights[rel]=max(weights.get(rel,0),min(.32,.13+sim*.28))
        results=[];k1=1.25;b=.68
        for doc in self.docs:
            score=0.0;matched=[]
            for term,qw in weights.items():
                tf=doc.tf.get(term,0)
                if not tf:continue
                df=max(1,self.df.get(term,1));idf=math.log(1+(self.n-df+.5)/(df+.5))
                denom=tf+k1*(1-b+b*doc.length/self.avgdl)
                score += qw*idf*(tf*(k1+1)/denom)
                if qw < .9 and len(matched)<4:matched.append(term)
            tlow=_ascii(doc.title)
            if qraw==tlow:score+=16
            elif qraw and qraw in tlow:score+=7
            if all(t in doc.title_tokens for t in qt):score+=4
            if score>0:
                results.append((score,doc,matched))
        results.sort(key=lambda x:(-x[0],x[1].title.casefold()))
        out=[]
        for score,doc,matched in results[:max(1,min(int(limit),30))]:
            out.append({'slug':doc.slug,'title':doc.title,'chapter':doc.chapter,'excerpt':doc.excerpt,'score':round(score,4),'semantic_matches':matched})
        return out


_CACHE: "OrderedDict[str, SemanticIndex]" = OrderedDict()
_CACHE_MAX=4


def _key(pages: Iterable[dict]) -> str:
    h=hashlib.blake2b(digest_size=16)
    for p in pages:
        text=str(p.get('plain_text') or p.get('excerpt') or '')
        h.update(str(p.get('slug') or '').encode('utf-8','ignore'));h.update(b'\0')
        h.update(str(p.get('title') or '').encode('utf-8','ignore'));h.update(b'\0')
        h.update(str(len(text)).encode());h.update(b':');h.update(text[:96].encode('utf-8','ignore'));h.update(text[-96:].encode('utf-8','ignore'))
    return h.hexdigest()


def index_for_pages(pages: list[dict]) -> SemanticIndex:
    key=_key(pages)
    idx=_CACHE.get(key)
    if idx is not None:
        _CACHE.move_to_end(key);return idx
    idx=SemanticIndex(pages);_CACHE[key]=idx
    while len(_CACHE)>_CACHE_MAX:_CACHE.popitem(last=False)
    return idx


def semantic_search(pages: list[dict], query: str, limit: int=12) -> list[dict]:
    return index_for_pages(pages).search(query,limit)
