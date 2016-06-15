#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
#
# Copyright (C) 2015 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Authors:
#   Alvaro del Castillo San Felix <acs@bitergia.com>
#

import json
import logging

import requests

from dateutil import parser

from grimoire.elk.enrich import Enrich


GITHUB = 'https://github.com/'

class GitEnrich(Enrich):

    def __init__(self, git, sortinghat=True, db_projects_map = None):
        super().__init__(sortinghat, db_projects_map)
        self.elastic = None
        self.perceval_backend = git
        self.index_git = "git"
        self.github_logins = {}
        self.github_token = None

    def set_elastic(self, elastic):
        self.elastic = elastic

    def set_github_token(self, token):
        self.github_token = token

    def get_field_date(self):
        return "metadata__updated_on"

    def get_field_unique_id(self):
        return "ocean-unique-id"

    def get_fields_uuid(self):
        return ["author_uuid", "committer_uuid"]

    def get_elastic_mappings(self):

        mapping = """
        {
            "properties": {
               "message_analyzed": {
                  "type": "string",
                  "index":"analyzed"
               }
           }
       }"""

        return {"items":mapping}


    def get_identities(self, item):
        """ Return the identities from an item.
            If the repo is in GitHub, get the usernames from GitHub. """
        identities = []

        commit_hash = item['data']['commit']
        github_repo = None
        if GITHUB in item['origin']:
            github_repo = item['origin'].replace(GITHUB,'').replace('.git','')

        if item['data']['Author']:
            username = None
            if self.github_token and github_repo:
                # Get the usename from GitHub
                username = self.get_github_login(item['data']['Author'], "author", commit_hash, github_repo)
            user = self.get_sh_identity(item['data']["Author"], username)
            identities.append(user)

        if item['data']['Commit'] and github_repo:
            username = None
            if self.github_token:
                # Get the username from GitHub
                username = self.get_github_login(item['data']['Commit'], "committer", commit_hash, github_repo)
            user = self.get_sh_identity(item['data']['Commit'], username)
            identities.append(user)

        return identities

    def get_sh_identity(self, git_user, username=None):
        # John Smith <john.smith@bitergia.com>
        identity = {}

        if username is None and self.github_token:
            # Try to get the GitHub login from the cache
            try:
                username = self.github_logins[git_user]
            except KeyError:
                pass

        name = git_user.split("<")[0]
        name = name.strip()  # Remove space between user and email
        email = git_user.split("<")[1][:-1]
        identity['username'] = username
        identity['email'] = email
        identity['name'] = name

        return identity

    def get_item_project(self, item):
        """ Get project mapping enrichment field """
        ds_name = "scm"  # data source name in projects map
        url_git = item['origin']
        try:
            project = (self.prjs_map[ds_name][url_git])
        except KeyError:
            # logging.warning("Project not found for repository %s" % (url_git))
            project = None
        return {"project": project}

    def get_github_login(self, user, rol, commit_hash, repo):
        """ rol: author or committer """
        login = None
        try:
            login = self.github_logins[user]
        except KeyError:
            # Get the login from github API
            GITHUB_API_URL = "https://api.github.com"
            commit_url = GITHUB_API_URL+"/repos/%s/commits/%s" % (repo, commit_hash)
            headers = {'Authorization': 'token ' + self.github_token}
            r = requests.get(commit_url, headers=headers)
            r.raise_for_status()
            logging.debug("Rate limit pending: %s" % (r.headers['X-RateLimit-Remaining']))

            commit_json = r.json()
            author_login = None
            if 'author' in commit_json and commit_json['author']:
                author_login = commit_json['author']['login']
            user_login = None
            if 'committer' in commit_json and commit_json['committer']:
                user_login = commit_json['committer']['login']
            if rol == "author":
                login = author_login
            elif rol == "committer":
                login = author_login
            else:
                logging.error("Wrong rol: %s" % (rol))
                raise RuntimeError
            self.github_logins[user] = login
            logging.debug("%s is %s in github" % (user, login))
        return login

    def get_rich_commit(self, item):
        eitem = {}
        # metadata fields to copy
        copy_fields = ["metadata__updated_on","metadata__timestamp","ocean-unique-id","origin"]
        for f in copy_fields:
            if f in item:
                eitem[f] = item[f]
            else:
                eitem[f] = None
        # The real data
        commit = item['data']
        # data fields to copy
        copy_fields = ["message","Author"]
        for f in copy_fields:
            if f in commit:
                eitem[f] = commit[f]
            else:
                eitem[f] = None
        # Fields which names are translated
        map_fields = {"commit": "hash","message":"message_analyzed","Commit":"Committer"}
        for fn in map_fields:
            if fn in commit:
                eitem[map_fields[fn]] = commit[fn]
            else:
                eitem[map_fields[fn]] = None
        eitem['hash_short'] = eitem['hash'][0:6]
        # Enrich dates
        author_date = parser.parse(commit["AuthorDate"])
        commit_date = parser.parse(commit["CommitDate"])
        eitem["author_date"] = author_date.replace(tzinfo=None).isoformat()
        eitem["commit_date"] = commit_date.replace(tzinfo=None).isoformat()
        eitem["utc_author"] = (author_date-author_date.utcoffset()).replace(tzinfo=None).isoformat()
        eitem["utc_commit"] = (commit_date-commit_date.utcoffset()).replace(tzinfo=None).isoformat()
        eitem["tz"]  = int(commit_date.strftime("%z")[0:3])
        # Other enrichment
        eitem["repo_name"] = item["origin"]
        # Number of files touched
        eitem["files"] = len(commit["files"])
        # Number of lines added and removed
        lines_added = 0
        lines_removed = 0
        for cfile in commit["files"]:
            if 'added' in cfile and 'removed' in cfile:
                try:
                    lines_added += int(cfile["added"])
                    lines_removed += int(cfile["removed"])
                except ValueError:
                    # logging.warning(cfile)
                    continue
        eitem["lines_added"] = lines_added
        eitem["lines_removed"] = lines_removed
        eitem["lines_changed"] = lines_added + lines_removed

        # author_name and author_domain are added always
        identity  = self.get_sh_identity(commit["Author"])
        eitem["author_name"] = identity['name']
        eitem["author_domain"] = self.get_identity_domain(identity)

        # committer data
        identity  = self.get_sh_identity(commit["Commit"])
        eitem["committer_name"] = identity['name']
        eitem["committer_domain"] = self.get_identity_domain(identity)

        # title from first line
        if 'message' in commit:
            eitem["title"] = commit['message'].split('\n')[0]
        else:
            eitem["title"] = None

        # If it is a github repo, include just the repo string
        if GITHUB in item['origin']:
            eitem['github_repo'] = item['origin'].replace(GITHUB,'').replace('.git','')
            eitem["url_id"] = eitem['github_repo']+"/commit/"+eitem['hash']

        if 'project' in item:
            eitem['project'] = item['project']

        if self.sortinghat:
            eitem.update(self.get_item_sh(item, "Author"))

        if self.prjs_map:
            eitem.update(self.get_item_project(item))

        eitem.update(self.get_grimoire_fields(commit["AuthorDate"], "commit"))

        return eitem

    def enrich_items(self, commits):
        max_items = self.elastic.max_items_bulk
        current = 0
        bulk_json = ""

        url = self.elastic.index_url+'/items/_bulk'

        logging.debug("Adding items to %s (in %i packs)" % (url, max_items))

        for commit in commits:
            if current >= max_items:
                self.requests.put(url, data=bulk_json)
                bulk_json = ""
                current = 0

            rich_commit = self.get_rich_commit(commit)
            data_json = json.dumps(rich_commit)
            bulk_json += '{"index" : {"_id" : "%s" } }\n' % \
                (rich_commit[self.get_field_unique_id()])
            bulk_json += data_json +"\n"  # Bulk document
            current += 1
        self.requests.put(url, data = bulk_json)
