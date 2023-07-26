from IPython.display import clear_output
import wikipediaapi as wiki
import re
import numpy as np
import matplotlib.pyplot as plt
from sys import getsizeof
from time import time,sleep
import dill as pkl
import os
import shutil
#from zipfile import ZipFile
import zipfile

class DynamicClass:
            
    def __init__(self):
        self.save_path = ''
    
    @staticmethod
    def load(file_name):
        dummy = KnowledgeNet(None)#,language=None)
        loaded_variables = 0
        with open(file_name,'br') as fp:
            saved_variables = pkl.load(fp)
            try:
                for i,var in enumerate(saved_variables):
                    setattr(dummy,var,pkl.load(fp))
                    loaded_variables += 1
                    #print(f'imported {var}')
            except:
                print('cannot find the variables %s'%(', '.join(saved_variables[loaded_variables:])))

        print('Loaded %d member variables from %s'%(len(saved_variables),file_name))
        return dummy
    
    def save(self,file_name,overwrite=False):
        exists = os.path.exists(file_name)
        if exists and not overwrite:
            raise Exception(f'File {file_name} already exists!')
        
        self.save_path = file_name
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
        super().__init__()
        self.logging = []
        self.state = ''
        self.taskLogStart = 0
        self.verbose = 1
        self.root = []
        
        self.articles = {}
        self.open_categories = {}
        self.category_tree = {}
        self.closed_categories = []
        self.skip_rules = []
        self.skipped = []
        self.resetCollection()

        self.label_blacklist = ['Wikipedia articles incorporating','Webarchive template wayback links','Articles citing','Articles that','Wikipedia articles needing','All orphaned articles','Orphaned articles','Articles using','Pages with listed','Use dmy dates from','CS1']
        self.label_blacklist += ['Articles covered','Articles tagged','All articles','All Wikipedia articles','Articles with','.*Wikidata','Articles lacking','Articles needing','Articles containing','Articles requiring','Wikipedia articles in need of']


        self.language = language
        if not type(language) == type(None):
            self.initWiki()
        if not type(start_at) == type(None):
            self.startScan(start_at,depth,skip=skip,skip_rules=skip_rules,verbose=verbose)
        
    def initWiki(self):
        """
        Creates a connection to wikipedia which can be used to request articles and metainformation.
        """
        self.html_wiki = wiki.Wikipedia(self.language, extract_format=wiki.ExtractFormat.HTML)
        self.categry_label = {'de':'Kategorie','en':'Category'}[self.language]
        
    def setSkipRule(self,rules):
        """
        Define rules (Regex) to exclude Categories or articles.

        Args:
            rules (str / Regex): Regular expression. When evaluated true on the title of page the page is ommitted.
        """
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
        
        try:
            page = self.html_wiki.page(start_at)
        except:
            raise Exception('Connection to Wikipedia failed!')
            
        if not page.exists():
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
        self.indexInfo()
        return True

    def scanLevel(self,category,lvl,skip=[],skip_rules=[],verbose=1):               
        new_categories = 0
        new_articles = 0
        skipped = 0
        if category in self.closed_categories:
            self.log(f"The category '{category}' was skipped since it had been crawled before.")
            return new_articles,new_categories,skipped
        
        cat_page,cat_categories = self.getPageAndCategories(category)            
        if not cat_page.exists():
            self.log('Page %s was not found!'%category,level=0)
            self.closed_categories.append(category)
            return new_articles,new_categories,skipped
        
        category_members = self.getSubCategories(cat_page,category)
        
        for cat in category_members:
            if not self.checkValid(cat,set([cat]).union(cat_categories),skip,skip_rules):
                skipped += 1
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
    
    def getSubCategories(self,cat_page,category):
        repeats = 0
        while repeats < 3:
            try:
                category_members = cat_page.categorymembers.keys()
                return category_members
            except:
                repeats += 1
                print(f'Attempt {repeats}: Cannot collect categorymembers for {category}.')
                sleep(0.5)
        if repeats == 3:
            raise Exception('Connection to Wikipedia failed (3 times)!')

    def crawlDeeper(self,lvl=None,skip=[],skip_rules=[],verbose=1):
        if not type(lvl) == int:
            lvl = min(self.open_categories.values())
            
        next_categories = [cat for cat,l in self.open_categories.items() if l == lvl]
        new_categories = 0
        new_articles = 0
        skipped = 0
        
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
        return new_categories

    def indexInfo(self):
        print('Collected %d articles from %d categories.'%(len(self.articles),len(self.closed_categories)))

    def collect(self,links=True,text=False,ignore=[],ignore_rules=[],
                archive_path=None,zipped=False,save_interval=None,
                limit=None,verbose=1):
        
        """
        Collect links and/or text from all articles in the list.
        """
        start_at = self.collected
        if type(limit) == type(None):
            limit = len(self.articles)
        
        if not type(archive_path) == type(None):
            if os.path.exists(archive_path) and not os.path.isdir(archive_path):
                raise Exception(f'Folder {archive_path} is not a directory!')
            if not type(archive_path) == type(None) and not zipped and not os.path.exists(archive_path):
                os.mkdir(archive_path)
            if not type(archive_path) == type(None):
                self.archive_path = archive_path if not zipped else archive_path+'.zip'
        auto_save = self.save_path != '' and type(save_interval) == int

        txts = 0
        lnks = 0
        skpd = 0
        start = time()
        self.stalk_time_prediction = []
        self.newTask(verbose=verbose)
        target_pages = list(self.articles.keys())[start_at:start_at+limit]
        total = len(target_pages)
        for i,p in enumerate(target_pages):
            try:
                inherited_categories = self.retrieveCategories(p)          
                page,page_categories = self.getPageAndCategories(p)              
                total_cat = set(inherited_categories).union(page_categories)
                valid = self.checkValid(p,total_cat,ignore,ignore_rules)
                if valid:
                    self.collectArticle(p,links=links,text=text,page_obj=page,categories=inherited_categories)
                    if links:
                        lnks += len(self.links[p])
                    if text:
                        txts += self.pages[p] if type(self.pages[p]) == int else len(self.pages[p])
                        
            except KeyboardInterrupt:
                self._progresBar(i,total,start,lnks,txts,skpd,verbose)
                print('stopped by user')
                break
            except Exception as e:
                self.log(f"Exception while collecting {p}: {e}")
                skpd += 1
            
            self.collected += 1
            if auto_save and (i%save_interval == 0 or i+1 == total):
                self.save(self.save_path,overwrite=True)
            
            if (i+1)%10 == 0 or i+1 == total: 
                self._progresBar(i,total,start,lnks,txts,skpd,verbose)
                
    def _progresBar(self,i,total,start,lnks,txts,skpd,verbose):
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
        if lnks > 0:
            info += f' {lnks} links'
        if txts > 0:
            info += f' {txts} lines of text'
        if skpd > 0:
            info += f' {skpd} skipped'
        
        self.stalk_time_prediction.append([diff,wait])
        self.printStatus(info,verbose=verbose)
    
    def getPageAndCategories(self,page):
        """
        Collect page-object and save explicit categories
        Args:
            p (str): article name
        Return:
            tuple: page-object , category list
        """
        for repeat in range(3):
            try:
                page_obj = self.html_wiki.page(page)
                self.article_categories[page] = list(page_obj.categories.keys())

                if repeat > 0:
                    print(f'{page}: Download successfull after {repeat} failed trials.')
                return page_obj,self.article_categories[page]
            
            except Exception as e:
                if repeat < 2:
                    print(f'Problem while collecting {page}: {e}...',end="")
                    sleep(3)
                    self.initWiki()
                    sleep(3)
                    print('Reconnected to Wikipkedia')
        
        self.log(f'Skipped article {page} because of connection problems.',level=0)
        self.skipped_by_problem[page] = type(e) 
        raise Exception('Connection to Wikipedia failed!')
        
    
    def checkValid(self,p,total_cat,ignore,ignore_rules):
        """
        Check weather an article is valid according to the global and local ignor-rules.
        Args:
            p (str): Article name.
            
            total_cat (list): List of all categories of the page p.
            
            ignore (list): List of forbiden categories.
            
            ignore_rules (list): List of regular-expressions that are applied to the categories. 
                If at least one rule matches on one category, the article is ignored.
            
        """
        ignore_by_rule = []
        for cat in total_cat:
            for rule in ignore_rules + self.skip_rules:
                if re.match(rule,cat):
                    ignore_by_rule.append([cat,rule])
             
        if len(ignore_by_rule) > 0:
            self.skipped_by_rule[p] = ignore_by_rule
                    
        bad_cat = total_cat.intersection(ignore)
        if len(bad_cat) > 0:
            self.skipped_by_category[p] = bad_cat
            
        if len(ignore_by_rule) > 0 or len(bad_cat) > 0:
            self.log('Skipped article %s because of categories'%(p),level=1)
            return False
        
        return True
    
    def collectArticle(self,page,links=False,text=False,page_obj=None,categories=[]):
        if page in self.pages.keys():
            return False
            
        for repeat in range(3):
            try:
                if type(page_obj) == type(None):
                    page_obj = self.html_wiki.page(page)
                    
                if links:
                    self.links[page] = list(page_obj.links.keys())
                if text:
                    text = self.extractText(page_obj) 
                    if hasattr(self,'archive_path'):
                        self.pages[page] = len(text)
                        self.saveText(page,text,categories)
                    else:
                        self.pages[page] = text
                        
                return len(text)
                
            except Exception as e:
                if repeat < 2:
                    print(f'Problem while collecting {page}: {e}...',end="")
                    sleep(3)
                    self.initWiki()
                    sleep(3)
                    print('Reconnected to Wikipkedia')

        self.log(f'Skipped article "{page}" because of connection problems.',level=1)
        self.skipped_by_problem[page] = type(e)
        raise Exception('Connection to Wikipedia failed!')

    
    def extractText(self,page):
        """
        Extracts plain text content from an article.
        Args:
            page (str): Article name.

        Returns:
            list of lines (list)
        """
        lines = []
        res = re.findall('<p[^>]*>.*?</p>',page.text,flags= re.IGNORECASE | re.DOTALL)
        for p in res:
            p = re.sub('<.*?>','',p)
            p = re.sub('\s+',' ',p,)
            lines.append(p.strip())
        return [lns for lns in lines if len(lns) > 3]
    
    def saveText(self,page,lines,categories):
        title = re.sub('[^a-z0-9_-]','~',page.replace(' ','_'),flags=re.IGNORECASE)
        skip_label = len(self.categry_label)+1
        short_categories = [cat[skip_label:] for cat in categories]


        direct_categories = [cat[skip_label:] for cat in self.article_categories[page]]
        #filter by wikipedia related labals (blacklist)
        filtered_direct_categories = [cat for cat in direct_categories if not any([re.match(f"{rule}.*",cat) for rule in self.label_blacklist])]
        print_lines = [', '.join(short_categories)]+[', '.join(filtered_direct_categories)]+lines

        if re.match('.*?\.zip$',self.archive_path):
            with zipfile.ZipFile(self.archive_path,'a',compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(title+'.txt','\n'.join(print_lines)) 
                
        else:
            file_path = os.path.join(self.archive_path, title)
            with open(file_path+'.txt','w', encoding="utf-8") as fp:
                for l,line in enumerate(print_lines):
                    out = line+'\n' if l < len(print_lines)-1 else line
                    fp.write(out)
        
    def resetCollection(self,ask_before_deleting=True):
        """
        Delete the files containing the text and categories. The article list and category-tree will be maintained.
        """
        self.collected = 0
        self.links = {}
        self.pages = {}
        self.article_categories = {}
        
        self.skipped_by_rule = {}
        self.skipped_by_category = {}
        self.skipped_by_problem = {}
        
        if hasattr(self, 'archive_path'):
            if ask_before_deleting:
                ask_delelte = input('delete existing archive %s? [y/n]'%self.archive_path).strip()
                while not re.match('^[yn]$', ask_delelte):
                    print('Please type "y" to delte the file or "n" to keep the file.')
                    ask_delelte = input('delete existing archive %s? [y/n]'%self.archive_path).strip()
                    print('response: %s'%ask_delelte)
            else:
                ask_delelte = "y"
                 
            if ask_delelte == "y":
                if os.path.isfile(self.archive_path):
                    os.remove(self.archive_path)
                elif os.path.isdir(self.archive_path):
                    shutil.rmtree(self.archive_path)

    def printCategoryTree(self,max_lvl=None):
        """
        Print hierarchical tree of article categories up to level max_level.

        Args:
            max_lvl (int): maximal level that is dispayed.
        """
        if type(max_lvl) == type(None):
            max_lvl = max(self.articles.values())
        for root in self.root:
            cats = len([c for c,p in self.category_tree.items() if self.categry_label in c and root in p])
            arts = len([c for c,p in self.category_tree.items() if root in p and c in self.articles.keys()])
            print(f'{root} ({cats} C ; {arts} A)')
            if max_lvl > 0:
                self._printSubcats(root,0,max_lvl-2)
        
    def _printSubcats(self,cat,lvl,max_lvl):
        subcats = [c for c,p in self.category_tree.items() if cat in p]
        for ct in subcats:
            if self.categry_label in ct:
                indent = ' '*4*(lvl+1)
                name = ct.replace(f'{self.categry_label}:','')
                cats = len([c for c,p in self.category_tree.items() if self.categry_label in c and ct in p])
                arts = len([c for c,p in self.category_tree.items() if ct in p and c in self.articles.keys()])
                print(f'{indent}{name} ({cats} C ; {arts} A)')
                if not lvl > max_lvl:
                    self._printSubcats(ct,lvl+1,max_lvl)
    
    def retrieveCategories(self,article):
        """
        Collect all categories an article belongs to, including inhereted categories.

        Args:
            artilce (str): name of article.

        Returns:
            list of categories (str)
        """
        ancestor_generation = set(self.category_tree[article])
        ancestors = set([])
        while len([a for a in ancestor_generation if not a == []]) > 0 and len(ancestors) < 100:
            next_ancestor_generation = set([])
            for parent in ancestor_generation:
                next_ancestor_generation.update(self.category_tree[parent])
            next_ancestor_generation.difference_update(ancestors)
            ancestor_generation = next_ancestor_generation
            ancestors.update(ancestor_generation)
        return list(ancestors)
  

    def retrieveNetwork(self):
        """
        Counts how often other the remaining articles from the list point to the respective artilce. 
        In a second list, also articles that are not on the list are considered.

        Returns:
            inside (map): article from list : count of links to this artilce

            outside (map): artilce not from list : count of links to this artilce
        """
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
                