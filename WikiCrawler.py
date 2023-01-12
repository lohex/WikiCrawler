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
        self.state = ''
        self.taskLogStart = 0
        self.verbose = 1
        
        self.skipped = []
        self.skip_rules = []
        self.root = []
        
        self.articles = {}
        self.open_categories = {}
        self.category_tree = {}
        self.closed_categories = []
        self.article_categories = {}
        
        self.links = {}
        self.pages = {}
        
        self.language = language
        if not type(language) == type(None):
            self.initWiki()
        if not type(start_at) == type(None):
            self.startScan(start_at,depth,skip=skip,skip_rules=skip_rules,verbose=verbose)
        
    def initWiki(self):
        self.html_wiki = wiki.Wikipedia(self.language, extract_format=wiki.ExtractFormat.HTML)
        self.categry_label = {'de':'Kategorie','en':'Category'}[self.language]
        
    def setSkipRule(self,rules):
        if type(rules) == str:
            rules = [rules]
            
        add_counter = 0
        for rule in rules:
            if not rule in self.skip_rules:
                self.skip_rules.append(rule)
                add_counter += 1
        self.log('Appended %d new skip_rules.'%add_counter,level=0)
        
    def startScan(self,start_at,depth=3,skip=[],skip_rules=[],verbose=1):
        self.newTask(verbose=verbose)
        
        if not self.html_wiki.page(start_at).exists():
            self.log('Category %s does not exist!'%start_at,level=0)
            return False
        
        self.log('Start crawling categories starting at %s.'%start_at,level=0)
        if not start_at in self.category_tree.keys():
            self.root.append(start_at)
            self.category_tree[start_at] = []
            
        dn_art,dn_cat,dn_skip = self.scanLevel(start_at,0,skip=skip,skip_rules=skip_rules,verbose=1)
        self.log('Scanned on level 1: found %d pages and %d subcategories, %d skipped.'%(dn_art,dn_cat,dn_skip),level=0)
        for d in range(1,depth):
            found = self.crawlDeeper(lvl=d,skip=skip,skip_rules=skip_rules,verbose=verbose)
            if found == 0:
                break
                
        self.printStatus()
        return True

    def scanLevel(self,category,lvl,skip=[],skip_rules=[],verbose=1):       
        # only for functional savety validation
        if category in self.closed_categories:
            raise Exception("Category %s crawled twice!"%category)
        
        new_categories = 0
        new_articles = 0
        skipped = 0
        
        cat_page = self.html_wiki.page(category)
        if not cat_page.exists():
            self.log('Page %s was not found!'%category,level=0)
            self.closed_categories.append(category)
            return new_articles,new_categories,skipped
        
        for cat in cat_page.categorymembers.keys():
            skipped_by_rule = False
            for rule in skip_rules + self.skip_rules:
                if re.match(rule,cat):
                    skipped_by_rule = True
            
            if skipped_by_rule or cat in skip:
                self.skipped.append(cat)
                skipped += 1
                self.log('skip %s (from %s)'%(cat,category),level=1)
                continue
            
            parts = cat.split(':')
            if len(parts) > 1 and parts[0] == self.categry_label: #member category
                if not cat in self.open_categories.keys() and not cat in self.category_tree.keys():
                    self.open_categories[cat] = lvl+1
                    new_categories += 1
                    
            else: #member article
                if not cat in self.articles.keys():
                    self.articles[cat] = category
                    new_articles += 1

            if not cat in self.category_tree.keys():
                self.category_tree[cat] = []
            self.category_tree[cat].append(category)
                    
        self.closed_categories.append(category)
        return new_articles,new_categories,skipped
    
    def crawlDeeper(self,lvl=None,skip=[],skip_rules=[],verbose=1):
        if not type(lvl) == int:
            lvl = min(self.open_categories.values())
            
        next_categories = [cat for cat,l in self.open_categories.items() if l == lvl]
        new_categories = 0
        new_articles = 0
        skipped = 0
        arts_init = len(self.articles)
        for nc,cat in enumerate(next_categories):
            dn_art,dn_cat,dn_skip = self.scanLevel(cat,lvl,skip=skip,skip_rules=skip_rules)  
                
            new_categories += dn_cat
            new_articles += dn_art
            skipped += dn_skip
            base_status = 'Crawled %d/%d categories. Found %d pages and %d subcategories, %d skipped.'
            status_message = base_status%(nc+1,len(next_categories),new_articles,new_categories,skipped)
            del self.open_categories[cat]
            self.printStatus(status_message,verbose=verbose)
        
        base_message = 'Scanned on level %d: found %d pages and %d subcategories, %d skipped.'
        message = base_message%(lvl+1,new_articles,new_categories,skipped)
        self.log(message,level=0)
        self.printStatus('Done')
        return new_categories

    def collect(self,links=True,text=False,ignore=[],ignore_rules=[],limit=None,verbose=1):
        if type(limit) == type(None):
            limit = len(self.articles)
        
        lnks = 0
        start = time()
        
        self.newTask(verbose=verbose)
        target_pages = list(self.articles.keys())[:limit]
        total = len(target_pages)
        for i,p in enumerate(target_pages):
                
            cat_heridity = self.retrieveCategories(p)
            page = self.html_wiki.page(p)
            have_cat = set(cat_heridity).union(page.categories.keys())
                
            ignore_by_rule = False
            for cat in have_cat:
                for rule in ignore_rules + self.skip_rules:
                    if re.match(rule,cat):
                        ignore_by_rule = True
                            
            bad_cat = have_cat.intersection(ignore)
            if ignore_by_rule or len(bad_cat) > 0:
                self.log('skip article %s by categories'%(p),level=1)
                self.skipped.append(p)
            else:
                self.collectArticle(p,links=links,text=text)
                if links:
                    lnks += len(self.links[p])
                            
            if i%10 == 0 or i+1 == total:         
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
                self.printStatus(info,verbose=verbose)
    
    def collectArticle(self,page,links=False,text=False,page=None):
        for tried in range(3):
            try:

                if type(page) == type(None):
                    page_obj = self.html_wiki.page(page)
                    
                self.article_categories[page] = page_obj.categories.keys()
                if links:
                    self.links[page] = list(page_obj.links.keys())
                if text:
                    text = self.extractSectionwise(page)
                    self.pages[page] = text
                
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
        for root in self.root:
            cats = len([c for c,p in self.category_tree.items() if self.categry_label in c and root in p])
            arts = len([c for c,p in self.category_tree.items() if root in p and c in self.articles.keys()])
            print(f'{root} ({cats} C ; {arts} A)')
            if max_lvl > 0:
                self.printSubcats(root,0,max_lvl-2)
        
    def printSubcats(self,cat,lvl,max_lvl):
        subcats = [c for c,p in self.category_tree.items() if cat in p]
        for ct in subcats:
            if self.categry_label in ct:
                indent = ' '*4*(lvl+1)
                name = ct.replace(f'{self.categry_label}:','')
                cats = len([c for c,p in self.category_tree.items() if self.categry_label in c and ct in p])
                arts = len([c for c,p in self.category_tree.items() if ct in p and c in self.articles.keys()])
                print(f'{indent}{name} ({cats} C ; {arts} A)')
                if not lvl > max_lvl:
                    self.printSubcats(ct,lvl+1,max_lvl)
    
    def retrieveCategories(self,article):
        ancestor_generation = set(self.category_tree[article])
        ancestors = [ancestor_generation]
        while len([a for a in ancestor_generation if not a == []]) > 0:
            ancestor_generation = set([])
            for parent in ancestors[-1]: 
                ancestor_generation.update(self.category_tree[parent])
            ancestors.append(ancestor_generation)
            
        categories = []
        for generateion in reversed(ancestors):
            for c in generateion:
                if not c in categories:
                    categories.append(c)
                    
        return categories
    ´
    def retrieveNetwork(self):
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
        self.outside = {p:c for p,c in sorted(outside.items(),key=lambda x:-x[1]) if not '(identifier)' in p and not 'Wikipedia:' in p}
        return self.network
    
    def printStatus(self,state=None,verbose=None):
        '''
        Print status message and prepend log messages.
        
        Args:
            state (str): message that is printed after log
            
            level (int): print log-level: 0 = none, 1 = only results or errors, 2 = include infos (e.g. skipped articles)
        '''
        
        clear_output(True)
        for lg in self.logging[self.taskLogStart:]:
            if lg['level'] < self.verbose:
                print(lg['message'])
        if not type(state) == type(None):
            self.state = state
            print(self.state)
        
    def log(self,message,level=1):
        self.logging.append({'message':message,'level':level})
        self.printStatus(self.state)
        
    def newTask(self,verbose=1):
        self.verbose = verbose
        self.taskLogStart = len(self.logging)
        
    def printProtocol(self,level=1):
        for lg in self.logging:
            if lg['level'] < level:
                print(lg['message'])
                