# Testrail Migrator
Tool for migrating data from testrail

## User flow
### Creating config 
1. Go to *Migrator settings* in nav bar
2. Press Add config
3. Fill out form
   1. Verbose name: Verbose name of config
   2. Testrail api url: url to testrail api ending with */index.php?/api/v2*.  
   Example: *https://<your.host>/index.php?/api/v2* **!NO BACKSLASH AT THE END**
   3. Testy attachments url: url that you use as attachments url, used for replacing attachment references in 
   text fields   
   Example: *https://<your.host>/attachments*
   **!NO BACKSLASH AT THE END**
   4. Custom fields matcher: json field for parsing attributes with prefix *custom_* from testrail cases to testy.  
   You can map several custom fields to one testy field, values will be appended and separated by custom field name.  
   Example: 
   ```json
   {
    "testrail_custom_field": "testy_field",
    "custom_steps": "scenario",
    "custom_preconds": "setup",
    "custom_description": "description"
    }
   ```
### Downloading testrail content
1. Go to *Download Objects* in nav bar. There we have dropdown menu with following options: *testrail projects*,   
*testrail milestones*, *testrail suites*, *testrail plans/runs*. Press needed option, and fill out form. Testrail  
authorization is *Basic Auth*.  
**Testy doesn't keep your testrail credentials anywhere you will have to provide them everytime**.
2. All list ids, like run ids or suite ids are string separated by comma.  
Example: *1, 2, 3, 4*
3. Download attachments: if you don't wish to download attachments (it is faster) leave checkbox empty.
4. Ignore completed: all completed milestones/plans etc will not be copied.
5. Backup filename: name to idetify your downloaded data from testrail, timestamp is appended at the end of name.  
*All downloaded data is kept in redis*.
### Uploading testrail content
1. Go to *Upload objects* in nav bar.
2. Use upload method according to download. If you used **download testrail projects**, for uploading use  
**upload testrail projects**.
3. Choose config you created and downloaded data with.
4. Choose your backup.
5. Provide testrail credentials.
6. Upload root runs: field that defines if you wish to upload test runs that have no milestones.

### Worth mentioning
1. Downloaded testrail projects are your backups. Deleting them won't remove them from redis.
2. Backups are visible for ALL USERS
3. Configs are visible for ALL USERS
4. **!!TESTRAIL USER YOU PROVIDE MUST HAVE READ RIGHTS FOR ALL INSTANCES INCLUDING USERS!!** 

