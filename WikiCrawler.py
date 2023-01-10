"""
Author: Lorenz Hexemer
"""

from IPython.display import clear_output
import wikipediaapi as wiki
import re
import numpy as np
import matplotlib.pyplot as plt
from sys import getsizeof
from time import time,sleep
import dill as pkl
import os

class DynamicClass:
            
    @staticmethod
    def load(file_name):
        dummy = KnowledgeNet(None)#,language=None)
        with open(file_name,'br') as fp:
            saved_variables = pkl.load(fp)
            for var in saved_variables:
                setattr(dummy,var,pkl.load(fp))
                #print(f'\tset {var} from file')

        print('Loaded %d member variables from %s'%(len(saved_variables),file_name))
        return dummy
    
    def save(self,file_name,overwrite=False):
        exists = os.path.exists(file_name)
        if exists and not overwrite:
            raise Exception(f'File {file_name} already exists!')
        
        no_save = ["<class 'function'>","<class 'method'>"]
        save_variables = [child for child in dir(self)
                  if not re.match('^__.*__$',child) and not str(type(getattr(self,child))) in no_save]
        
        with open(file_name,'bw') as fp:
            pkl.dump(save_variables,fp)
            for var in save_variables:
                pkl.dump(getattr(self,var),fp)
                
        print('Saved %d member variables to %s'%(len(save_variables),file_name))
    
    def update(self):
        class_name = self.__class__.__qualname__
        new = eval(f'{class_name}()')
        no_save = ["<class 'function'>","<class 'method'>"]
        save_variables = [child for child in dir(self)
                  if not re.match('^__.*__$',child) and not str(type(getattr(self,child))) in no_save]
        for var in save_variables:
            setattr(new,var,getattr(self,var))
        return new

class KnowledgeNet(DynamicClass):
    
    def __init__(self,language='en',start_at=None,depth=3,skip=[],skip_rules=[],verbose=1):
        self.logging = []
        self.protocol = []
        self.skipped = []
        self.state = ''

        self.articles = {}
        self.categories = {}
        self.category_tree = {}
        
        self.links = {}
        self.pages = {}
        
        self.language = language
        if not type(language) == type(None):
            self.initWiki()
        if not type(start_at) == type(None):
            self.root = start_at
            self.startScan(start_at,depth,skip=skip,skip_rules=skip_rules,verbose=verbose)
        
    def initWiki(self):
        self.html_wiki = wiki.Wikipedia(self.language) #,extract_format=wiki.ExtractFormat.HTML)
        self.categry_label = {'de':'Kategorie','en':'Category'}[self.language]
        
    def startScan(self,start_at,depth=3,skip=[],skip_rules=[],verbose=1):
        if start_at in self.category_tree.keys():
            self.log('Category %s was already part of the tree.'%start_at,level=0)
            self.finalReport('scan_categories',verbose=verbose)
            return False
        
        self.category_tree[start_at] = []
        dn_art,dn_cat,dn_skip = self.scanLevel(start_at,0,skip=skip,skip_rules=skip_rules,verbose=1)
        self.log('Scanned on level 1: found %d pages and %d subcategories, %d skipped.'%(dn_art,dn_cat,dn_skip),level=0)
        for d in range(1,depth):
            found = self.crawlDeeper(skip=skip,skip_rules=skip_rules,verbose=verbose)
            if found == 0:
                break
        self.finalReport(verbose=verbose)
        return True

    def scanLevel(self,category,lvl,skip=[],skip_rules=[],verbose=1):
        cat_page = self.html_wiki.page(category)
        new_categories = 0
        new_articles = 0
        skipped = 0
        for cat in cat_page.categorymembers.keys():
            skipped_by_rule = False
            for rule in skip_rules:
                if re.match(rule,cat):
                    skipped_by_rule = True
            
            if skipped_by_rule or cat in skip:
                self.skipped.append(cat)
                skipped += 1
                self.log('[scanLevel] skipp %s (from %s)'%(cat,category),level=1)
                continue
                
            if not cat in self.category_tree.keys():
                self.category_tree[cat] = []
            self.category_tree[cat].append(category)
            parts = cat.split(':')
            if len(parts) > 1 and parts[0] == self.categry_label:
                if not cat in self.categories.keys():
                    self.categories[cat] = lvl+1
                    new_categories += 1
            else:
                if not cat in self.articles.keys():
                    self.articles[cat] = lvl
                    new_articles += 1

        return new_articles,new_categories,skipped
    
    def crawlDeeper(self,skip=[],skip_rules=[],verbose=1):
        max_lvl = max(self.categories.values())
        next_categories = [cat for cat,lvl in self.categories.items() if lvl == max_lvl]
        new_categories = 0
        new_articles = 0
        skipped = 0
        arts_init = len(self.articles)
        for nc,cat in enumerate(next_categories):
            skipped_by_rule = False
            for rule in skip_rules:
                if re.match(rule,cat):
                    skipped_by_rule = True
                    
            if skipped_by_rule or cat in skip:
                self.skipped.append(cat)
                skipped += 1
                self.log('[crawlDeeper] skipp %s (on level %d)'%(cat,max_lvl),level=1)
                continue

            if cat in self.categories.keys() and self.categories[cat] < max_lvl:
                self.log('Category %s already in tree.'%cat,level=0)
            dn_art,dn_cat,dn_skip = self.scanLevel(cat,max_lvl,skip=skip,skip_rules=skip_rules)  
                
            new_categories += dn_cat
            new_articles += dn_art
            skipped += dn_skip
            base_status = 'Crawled %d/%d categories. Found %d pages and %d subcategories, %d skipped.'
            status_message = base_status%(nc,len(next_categories),new_articles,new_categories,skipped)
            self.printStatus(status_message,level=verbose)
        
        base_message = 'Scanned on level %d: found %d pages and %d subcategories, %d skipped.'
        message = base_message%(max_lvl+1,new_articles,new_categories,skipped)
        self.log(message,level=0)
        return new_categories

    def collect(self,links=True,text=False,ignore=[],ignore_rules=[],verbose=1):
        lnks = 0
        start = time()
        total = len(self.articles)
            
        for i,p in enumerate(self.articles.keys()):
                
            cat_heridity = self.retriveCategories(p)
            page = self.html_wiki.page(p)
            have_cat = set(cat_heridity).union(page.categories.keys())
                
            ignore_by_rule = False
            for cat in have_cat:
                for rule in ignore_rules:
                    if re.match(rule,cat):
                        ignore_by_rule = True
                            
            bad_cat = have_cat.intersection(ignore)
            if ignore_by_rule or len(bad_cat) > 0:
                self.log('[collect] skipp article %s by categories'%(p),level=1)
                self.skipped.append(p)
            else:
                self.collectArticle(p,links=links,text=text)
                if links:
                    lnks += len(self.links[p])
                            
            if i%10 == 0 or i+1 == len(self.articles):         
                bar = '='*int(np.ceil((i+1)/total*30))
                    
                now = time()
                diff = np.round(now-start)
                pro = (i+1)/total
                wait = np.round((1-pro)/pro*diff)
                run_time = f'{diff} s'
                if diff > 60:
                    mins = int(diff//60)
                    rest = int(diff%60)
                    run_time = f'{mins} min {rest:02d} s'
                wait_time = f'{wait} s'
                if wait > 60:
                    mins = int(wait//60)
                    rest = int(wait%60)
                    wait_time = f'{mins} min {rest:02d} s'
                    
                info = f'Collecting: [{bar:<30}] {int(pro*100):3d} % ({i+1}/{total} pages)'
                info += f'\n running: {run_time} ; remaining: {wait_time} s \n'
                if links:
                    info += f' {lnks} links'
                if text:
                    size = getsizeof(self.pages)
                    oom = int(np.log(size)//np.log(1024))
                    size /= 1024**oom
                    unit = ['B','KB','MB','GB'][oom]
                    info += f' {size:.2f} {unit} of text'
                if len(self.skipped) > 0:
                    info += f' {len(self.skipped)} skipped'
                self.printStatus(info)
        self.finalReport(verbose=verbose)
    
    def collectArticle(self,p,links=False,text=False,page=None):
        for tried in range(3):
            try:
                if type(page) == type(None):
                    page = self.html_wiki.page(p)
                    
                if links:
                    self.links[p] = list(page.links.keys())
                if text:
                    text = self.extractSectionwise(page)
                    self.pages[p] = text
                
                return True

            except:
                print('Network problem loading "%s"'%p,end='')
                for r in range(30):
                    sleep(2)
                    print('.',end='')
                            
                if tried < 2:
                    print(' try again.')
                else:
                    print("don't try again.")
                    self.log('skip "%s" for network problems.'%p,level=1)
                    return False

    
    def extractSectionwise(self,section):
        sects = {section.title : section.text}
        for subs in section.sections:
            if not subs.title in ['See also', 'References', 'Notes', 'Further reading', 'External links']:
                nuw_subs_sects = self.extractSectionwise(subs)
                sects.update(nuw_subs_sects)
        return sects
    
    def printCategoryTree(self,max_lvl=None):
        if type(max_lvl) == type(None):
            max_lvl = max(self.articles.values())
        self.printSubcats(self.root,0,max_lvl)
        
    def printSubcats(self,cat,lvl,max_lvl):
        subcats = [c for c,p in self.category_tree.items() if cat in p]
        for ct in subcats:
            if self.categry_label in ct:
                indent = ' '*4*lvl
                name = ct.replace(f'{self.categry_label}:','')
                cats = len([c for c,p in self.category_tree.items() if self.categry_label in c and ct in p])
                arts = len([c for c,p in self.category_tree.items() if ct in p and c in self.articles.keys()])
                print(f'{indent}{name} ({cats} C ;{arts} A)')
                if not lvl+1 > max_lvl:
                    self.printSubcats(ct,lvl+1,max_lvl)
    
    def retriveCategories(self,article):
        ancestor_generation = self.category_tree[article]
        ancestors = [ancestor_generation]
        while len([a for a in ancestor_generation if not a == []]) > 0:
            ancestor_generation = []
            for parent in ancestors[-1]:
                ancestor_generation += self.category_tree[parent]
            ancestors.append(ancestor_generation)
            
        return [par for generation in reversed(ancestors) for par in generation]
    
    def retriveNetwork(self):
        network = {}
        outside = {}
        for page,link_list in self.links.items():
            for lnk in link_list:
                if lnk in self.links.keys():
                    if not lnk in network.keys():
                        network[lnk] = 0
                    network[lnk] += 1
                else:
                    if not lnk in outside.keys():
                        outside[lnk] = 0
                    outside[lnk] += 1

        self.network = {p:c for p,c in sorted(network.items(),key=lambda x:-x[1])}
        self.outside = {p:c for p,c in sorted(outside.items(),key=lambda x:-x[1])}
        return self.network
    
    def printStatus(self,state=None,level=2):
        '''
        Print status message and prepend log messages.
        
        Args:
            state (str): message that is printed after log
            
            level (int): print log-level: 0 = none, 1 = only results or errors, 2 = include infos (e.g. skipped articles)
        '''
        clear_output(True)
        for lg in self.logging:
            if lg['level'] < level:
                print(lg['message'])
        if not type(state) == type(None):
            self.state = state
            print(self.state)
        
    def log(self,message,level=1):
        self.logging.append({'message':message,'level':level})
        #self.printStatus(self.state)
        
    def finalReport(self,verbose=1):
        self.printStatus(level=verbose)
        self.protocol += self.logging
        self.logging = []
        
    def printProtocol(self,level=1):
        for lg in self.protocol:
            if lg['level'] < level:
                print(lg['message'])
                