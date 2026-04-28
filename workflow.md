1. check mails for project requests from comunica 2x per hour on weekdays
2. receive request by email in gmail
    - identify deadline
    - identify workload in hours
    - task (1/1 = translation, 1/2 = review) by reading end of project_ID e.g. "2026/4311/EN » DE/1/1"
    - check calendar and schedule with the indentified information, if possible (condition: not more than 8h on weekdays, for review count +15min for discussion/LQA)
    - press in-email button to accept
        if no time in schedule: asked me for confirmation before reject
    - if accept is confirmed (-> new xtrf window "confirmation", "start" email, job appears in xtrf job list), move the request email into gmail "Process" folder; if not confirmed (link not valid, request rejected, project taken, no start email, then forget the data)
!IMPORTANT! At this point start writing to a memory or log file on which projects you started working on and at what state they are at the moment. Once a month we can archive it. I plan to build this workflow as an agent, and I would tell you about manual steps I made.
3. receive start mail, in email
    - click/open link "Open Job Manager" to XTRF -> You land on the project page in XTRF (does not require login)
    - For your Information: The XTRF job list is here: https://comunicadk.s.xtrf.eu/vendors/#/jobs (requires login, see env)
        - see XTRF_login_page.html for css path and so on
4. in Browser in job mnager xtrf: 
    4.1 
        - identify job number without non-alphanumeric characters, e.g. "2026/4311/EN » DE/1/1"
        - identify project number RTC_2604_P0732 (RTC is the client ID)create folder e.g. "20264311ENDE11_RTC_2604_P0732" under C:\Users\utasc\OneDrive\ArbeitNEU\Comunica DK
        - in this folder, create a folder "pre-processing"
    
    4.2 download files
        - if files, download files under "received files" into the created folder
        - unzip
            - the relevant file is usually a docx file that end with Clean_XTM.docx, for reference
            - don't do anything with these files.
    
    4.3 Create prject glossary
        - identify EPO title in EN and DE
            - extract bilingual terms from the title
            - save the terms in a csv file with header EN,DE, in the input folder of the code base:  C:\Users\utasc\OneDrive\Dokumente\Code\Python\patent-translation-agent\term-extract\input\glossary_{project_name}.csv (e.g. glossary_RTC_2604_P0732)
- write the state of the project into your memory

    - Expected: 
        - CAT tool = XTM to be delivered via XTM, - login sometimes highlighted in yellow in login table, save login table info (it doesnt change normally):
        Link: https://word.welocalize.com/project-manager-gui/login.jsp?client=IP#!/login
        Company name: IP (this stands for all minor clients, only major clients have a different company name, this is relevant on the login page, by default it is on IP)
        Credentials: see env XTM Workbench
        
    - identify client (certain specs/terminology might apply, e.g client = Ford, different company at XTM login, there are no client-specific instructions yet)
    - see patent-translation-agent/XTRF_project_site.html for css path
        - project info is on side pane
        - downloads under "received files" in the main pane, usually when it is a review, but that is not consistent.
        - EPO title:in main pane
5. click/open XTM link in XTRF Job Manager (it is unspecific) -> you land on the login page: https://word.welocalize.com/project-manager-gui/login.jsp?client=IP#!/login
    - see XTM_login_page.html for css selectors and so on
    - login, always use this preferred login: XTM_WORKBENCH_USERNAME5 and XTM_WORKBENCH_PASSWORD5 if this does not work, notify me before running a sequence trying the other, I am to notify the project manager about this.
    - after login you land in Configuration tab of XTM (normal clients -> nothing to do here)
    - go to task tab -> it opens with the "active" projects filter
    - find the Project number in the first column 
    - if you dont find the file, activate the "planned" filter, or the "closed" filter; if the project is in there or nowhere, notify me.
    - if you find the project, open the project link
6. in the XTM project workbench, the project will not be active because it is not yet "accepted", ignore that fact
    - First, download the bilingual excel file before doing any work. This is very important. After finishing translation/review, we can compare and track the changes for LQA. Download like this:
        - find the menu bar
        - in the menu bar, find the preview menu
        - in the preview menu, click on the "Excel extended table" option
        - a green bar with a link pops up in the right down corner
        - click the popup download link -> an explorer window opens
        - navigate to your folder/pre-processed and save the excel file
        - back in the XTM  project's workbench, accept the task. The accept button is above the menu bar.
        - copy the saved excel file to documents/code/python/patent-translation-agent/term-extract/input
        - For 1/1 tasks, name it "_to-be-translated". It is normally machine translation. This means, that if it is just generic machine translation with no especially trained machine (Ford has one), you better go to IP translator word plugin for translation first.
        - For 1/2 tasks name it "_to-be-reviewed". It should be human translation. You need to fill in an LQA form called "Score Card" there are 2 different kinds of Score Cards. One from IP Park, which is generic and doesnt require detailed tracked changes. And another one, that requires tracked changes and translator evaluation.
7. ONLY FOR MANUAL TRANSLATION IN IP-APPIFY Plugin: Run excel_to_word_table.py.
    - Exports ID and Source column into docx file.
    
8. ONLY FOR TRANSALTION (task 1/1) Run ipappify_translate.py (This serves as a pre-translation for terminology analysis. 1/1 need to run a 2. time through translation, then with clean glossary.)
    - Translates the file *Clean_XTM.docx.xsls  with the IP translation plugin in Word, via API 
    - use this unless it's a client where MT is proven to be good to start with. 
    - the translation is pasted into the target column of the excel file *_translated.xslx
9. ONLY WHEN USING IP.APPFY MANUALLY: Run word_to_excel_target.py 
    - Imports the translated column into the third column of the orininal and renames the file to _translated. 
    
10. Run the LLM_verb_comparison_xslx.py scripts in the term-extract folder to check fo inconsistent verb use.
    - The script sends batches of 15 segments to LLM (deepseek/deepseek-chat-v3-0324) to analyze verb pairs. It outputs a list of verbs per segment, a glossary of most used (canonical = >60%) translations and an flag table with deviations from this canonical translation. It flags the deviations, but if less then 60% for one translation, it flags all target terms. It separates case 1 (source term has varous target translations) and case 2 (same translation for various source terms) It adds the results as additional column to the Excel file.
11. Run the LLM_noun_comparison.py script in the term-extract folder to check for inconsistent noun phrases.
    - The script like under verb extraction but then for noun phrases, longest first. It sends result back to LLM to be evaluated for false positives.
    - TODO: new column is still overwriting the existing status column not being inserted as new column.
12. Run merge_glossaries.py
    - this consolidates the comparison, project and standard glossary into the project glossary
    - manually clean this glossary
    12.1 ONLY FOR 1/1 tasks (translation)
        - rerun translation, this time with the cleaned project glossary
    12.2 FOR 1/2 tasks (Revision) and 1/1 tasks after the 2nd translation run
        - Run LLM_glossary_check_xlsx.py
13. Run linter.
14. Revision of _translated_checks.xlsx:
    - TODO: consolidate annotated segments in a mobile view (to be programmed), 
    - revise the translation
15. Copy and paste the segments into XTM Workbench
    - open XTM Workbench project in browser
    - load from the revised _translated_checks.xlsx the segments according to the IDs (XTM Workbench ID = ID in xlsx)
    - paste them in the workbench
    - confirm every segment
16. Download Xbench report
17. Download target docx (files) and bilingual pdf (preview)
    - save with naming convention
18. STOP HERE, save state and notify me.
    - A human (I) has to approve the translation on the platform 
    - When approved, you will be notified to resume.
19. HUMAN ONLY: close Workbench window and go to XTM task list
    - find project, click on the 3 dots and re-assign back to group 
    - only press the close button in the workbench if you are asked to close a project (e.g. as a reviewer)
20. Open Xbench file run checks, create QA report, safe in project folder
21. Open XTRF project page
    - upload the docx, pdf and QA report xlsx and for Review (1/2) also the score card and when necessary also a translator's notes file.
    - Click Finish button
22. Move all the file from the code base input/output folders into the project/pre-processing folder

    