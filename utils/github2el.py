#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Github Pull Requests loader for Elastic Search
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
# TODO: Just a playing script yet.
#     - Use the _bulk API from ES to improve indexing

import argparse
from datetime import datetime
import json
import logging
import requests


def parse_args ():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--owner", required = True,
                        help = "github owner")
    parser.add_argument("-r", "--repository", required = True,
                        help = "github repository")
    parser.add_argument("-t", "--token", required = True,
                        help = "github access token")
    parser.add_argument("-e", "--elasticsearch_host",  default = "127.0.0.1",
                        help = "Host with elasticsearch" + \
                        "(default: 127.0.0.1)")
    parser.add_argument("--elasticsearch_port",  default = "9200",
                        help = "elasticsearch port " + \
                        "(default: 9200)")
    parser.add_argument("--delete",  action = 'store_true',
                        help = "delete repository data in ES")


    args = parser.parse_args()
    return args

def getGeoPoint(location):
    geo_point = geo_code = None

    if location in geolocations:
        geo_point = geolocations[location]

    else:
        url = 'https://maps.googleapis.com/maps/api/geocode/json'
        params = {'sensor': 'false', 'address': location}
        r = requests.get(url, params=params)

        try:
            geo_code = r.json()['results'][0]['geometry']['location']
        except:
            logging.info("Can't find geocode for " + location)

        if geo_code:
            geo_point = {
                "lat": geo_code['lat'],
                "lon": geo_code['lng']
            }
            geolocations[location] = geo_point


    return geo_point


def getTimeToCloseDays(pull):
    review_time = None

    if pull['closed_at']is None or pull['created_at'] is None:
        return review_time

    # closed_at - created_at
    closed_at = \
        datetime.strptime(pull['closed_at'], "%Y-%m-%dT%H:%M:%SZ")
    created_at = \
        datetime.strptime(pull['created_at'], "%Y-%m-%dT%H:%M:%SZ")

    seconds_day = float(60*60*24)
    review_time = \
        (closed_at-created_at).total_seconds() / seconds_day
    review_time = float('%.2f' % review_time)

    return review_time

def getGithubUser(login):

    if login is None:
        return None

    url = github_api + "/users/" + login

    r = requests.get(url, verify=False,
                     headers={'Authorization':'token ' + auth_token})
    user = r.json()

    users[login] = user

    # Get the public organizations also
    url += "/orgs"
    r = requests.get(url, verify=False,
                     headers={'Authorization':'token ' + auth_token})
    orgs = r.json()

    users[login]['orgs'] = orgs

    return user


def getUserEmail(login):
    email = None

    if login not in users:
        user = getGithubUser(login)
    else: user = users[login]

    if 'email' in user:
        email = user['email']

    return email


def getUserOrg(login):
    company = None

    if login not in users:
        user = getGithubUser(login)
    else: user = users[login]

    if 'company' in user:
        company = user['company']

    if company is None:
        company = ''
        # Return the list of orgs
        for org in users[login]['orgs']:
            company += org['login'] +";;"
        company = company[:-2]

    return company

def getUserName(login):
    name = None

    if login not in users:
        user = getGithubUser(login)
    else: user = users[login]

    if 'name' in user:
        name = user['name']

    return name

def getUserLocation(login):
    location = None

    if login not in users:
        user = getGithubUser(login)
    else: user = users[login]

    if 'location' in user:
        location = user['location']

    return location

def getUserGeoLocation(login):

    geo_point = None

    location = getUserLocation(login)

    if location is not None:
        geo_point = getGeoPoint(location)

    if geo_point and 'location' in geo_point:
        del geo_point['location']  # convert to ES geo_point format

    return geo_point



def getRichPull(pull):
    rich_pull = {}
    rich_pull['id'] = pull['id']
    rich_pull['time_to_close_days'] = getTimeToCloseDays(pull)

    rich_pull['user_login'] = pull['user']['login']
    rich_pull['user_name'] = getUserName(rich_pull['user_login'])
    rich_pull['user_email'] = getUserEmail(rich_pull['user_login'])
    rich_pull['user_org'] = getUserOrg(rich_pull['user_login'])
    rich_pull['user_location'] = getUserLocation(rich_pull['user_login'])
    rich_pull['user_geolocation'] = getUserGeoLocation(rich_pull['user_login'])
    if pull['assignee'] is not None:
        rich_pull['assignee_login'] = pull['assignee']['login']
        rich_pull['assignee_name'] = getUserName(rich_pull['assignee_login'])
        rich_pull['assignee_email'] = getUserEmail(rich_pull['assignee_login'])
        rich_pull['assignee_org'] = getUserOrg(rich_pull['assignee_login'])
        rich_pull['assignee_location'] = getUserLocation(rich_pull['assignee_login'])
        rich_pull['assignee_geolocation'] = getUserGeoLocation(rich_pull['assignee_login'])
    else:
        rich_pull['assignee_name'] = None
        rich_pull['assignee_login'] = None
        rich_pull['assignee_email'] = None
        rich_pull['assignee_org'] = None
        rich_pull['assignee_location'] = None
        rich_pull['assignee_geolocation'] = None
    rich_pull['title'] = pull['title']
    rich_pull['state'] = pull['state']
    rich_pull['created_at'] = pull['created_at']
    rich_pull['updated_at'] = pull['updated_at']
    rich_pull['closed_at'] = pull['closed_at']
    rich_pull['url'] = pull['html_url']
    labels = ''
    if 'labels' in pull:
        for label in pull['labels']:
            labels += label['name']+";;"
    if labels != '':
        labels[:-2]
    rich_pull['labels'] = labels

    return rich_pull


def getCacheFromES(_type, _key):
    """ Get cache data for items of _type using _key as the cache dict key """

    cache = {}
    res_size = 100  # best size?
    _from = 0

    elasticsearch_type = _type

    url = elasticsearch_url + "/"+elasticsearch_index_github
    url += "/"+elasticsearch_type
    url += "/_search" + "?" + "size=%i" % res_size
    r = requests.get(url)
    type_items = r.json()

    if 'hits' not in type_items:
        logging.info("No github %s data in ES" % (_type))

    else:
        while len(type_items['hits']['hits']) > 0:
            for hit in type_items['hits']['hits']:
                item = hit['_source']
                cache[item[_key]] = item
            _from += res_size
            r = requests.get(url+"&from=%i" % _from)
            type_items = r.json()

    return cache


def geoLocationsFromES():

    return getCacheFromES("geolocations", "location")

def geoLocationsToES(geolocations):

    elasticsearch_type = "geolocations"

    for loc in geolocations:
        geopoint = geolocations[loc]
        location = geopoint.copy()
        location["location"] = loc
        # First upload the raw pullrequest data to ES
        data_json = json.dumps(location)
        url = elasticsearch_url + "/"+elasticsearch_index_github
        url += "/"+elasticsearch_type
        safe_loc = loc.encode('ascii', 'ignore')
        url += "/"+str("%s-%s-%s" % (location["lat"], location["lon"], safe_loc))
        requests.put(url, data = data_json)


def usersToES(users):

    elasticsearch_type = "users"  # github global users

    for login in users:

        # First upload the raw pullrequest data to ES
        data_json = json.dumps(users[login])
        url = elasticsearch_url + "/"+elasticsearch_index_github
        url += "/"+elasticsearch_type
        url += "/"+str(users[login]["id"])
        requests.put(url, data = data_json)

def usersFromES():

    return getCacheFromES("users", "login")

def getLastUpdateFromES(_type):

    last_update = None

    url = elasticsearch_url + "/" + elasticsearch_index_raw
    url += "/"+ _type +  "/_search"

    data_json = """
    {
        "aggs": {
            "1": {
              "max": {
                "field": "updated_at"
              }
            }
        }
    }
    """

    res = requests.post(url, data = data_json)
    res_json = res.json()

    if 'aggregations' in res_json:
        if "value_as_string" in res_json["aggregations"]["1"]:
            last_update = res_json["aggregations"]["1"]["value_as_string"]

    return last_update


def create_geopoints_map(_type):
    """ geopoints type is not created in dynamic mapping """
    geo_map = """
        {
            "properties": {
               "assignee_geolocation": {
                   "type": "geo_point"
               },
               "user_geolocation": {
                   "type": "geo_point"
               }
            }
        }
    """
    elasticsearch_type = _type
    url = elasticsearch_url + "/"+elasticsearch_index
    url_type = url + "/" + elasticsearch_type
    url_map = url_type+"/_mapping"
    requests.put(url_map, data=geo_map)

def initES():

    _types = ['pullrequests','issues_pullrequests']

    # Remove and create indexes. Create mappings.
    url_raw = elasticsearch_url + "/"+elasticsearch_index_raw
    url = elasticsearch_url + "/"+elasticsearch_index

    requests.delete(url_raw)
    requests.delete(url)

    requests.post(url_raw)
    requests.post(url)

    for _type in _types:
        create_geopoints_map(_type)


def pullrequets2ES(pulls, _type):

    create_geopoints_map(_type)

    elasticsearch_type = _type
    count = 0

    for pull in pulls:

        if not 'head' in pull.keys() and not 'pull_request' in pull.keys():
            # And issue that it is not a PR
            continue

        # print pull['updated_at']

        # First upload the raw pullrequest data to ES
        data_json = json.dumps(pull)
        url = elasticsearch_url + "/"+elasticsearch_index_raw
        url += "/"+elasticsearch_type
        url += "/"+str(pull["id"])
        requests.put(url, data = data_json)

        # The processed pull including user data and time_to_close
        rich_pull = getRichPull(pull)
        data_json = json.dumps(rich_pull)
        url = elasticsearch_url + "/"+elasticsearch_index
        url += "/"+elasticsearch_type
        url += "/"+str(rich_pull["id"])
        requests.put(url, data = data_json)

        count += 1

    return count

def getPullRequests(url):
    url_next = url
    prs_count = 0
    last_page = None
    page = 1

    url_next += "&page="+str(page)

    while url_next:
        logging.info("Get issues pulls requests from " + url_next)
        r = requests.get(url_next, verify=False,
                         headers={'Authorization':'token ' + auth_token})
        pulls = r.json()
        prs_count += pullrequets2ES(pulls, "pullrequests")

        logging.info(r.headers['X-RateLimit-Remaining'])

        url_next = None
        if 'next' in r.links:
            url_next = r.links['next']['url']  # Loving requests :)

        if not last_page:
            last_page = r.links['last']['url'].split('&page=')[1].split('&')[0]

        logging.info("Page: %i/%s" % (page, last_page))

        page += 1

    return prs_count

def getIssuesPullRequests(url):
    _type = "issues_pullrequests"
    prs_count = 0
    last_page = page = 1
    last_update = getLastUpdateFromES(_type)
    last_update = None  # broken order in github API
    if last_update is not None:
        logging.info("Getting issues since: " + last_update)
        url += "&since="+last_update
    url_next = url

    while url_next:
        logging.info("Get issues pulls requests from " + url_next)
        r = requests.get(url_next, verify=False,
                         headers={'Authorization':'token ' + auth_token})
        pulls = r.json()

        prs_count += pullrequets2ES(pulls, _type)

        logging.info(r.headers['X-RateLimit-Remaining'])

        url_next = None
        if 'next' in r.links:
            url_next = r.links['next']['url']  # Loving requests :)

        if last_page == 1:
            if 'last' in r.links:
                last_page = r.links['last']['url'].split('&page=')[1].split('&')[0]

        logging.info("Page: %i/%s" % (page, last_page))

        page += 1

    return prs_count


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    logging.getLogger("requests").setLevel(logging.WARNING)

    args = parse_args()

    github_owner = args.owner
    github_repo = args.repository
    auth_token = args.token

    elasticsearch_url = "http://"
    elasticsearch_url += args.elasticsearch_host + ":" + args.elasticsearch_port
    elasticsearch_index_github = "github"
    elasticsearch_index = elasticsearch_index_github + \
        "_%s_%s" % (github_owner, github_repo)
    elasticsearch_index_raw = elasticsearch_index+"_raw"

    initES()  # until we have incremental support, always from scratch
    users = usersFromES()
    geolocations = geoLocationsFromES()

    github_per_page = 20  # 100 in other items. 20 for pull requests
    github_api = "https://api.github.com"
    github_api_repos = github_api + "/repos"
    url_repo = github_api_repos + "/" + github_owner +"/" + github_repo

    url_pulls = url_repo + "/pulls"
    url_issues = url_repo + "/issues"

    url_params = "?per_page=" + str(github_per_page)
    url_params += "&state=all"  # open and close pull requests
    url_params += "&sort=updated"  # sort by last updated
    url_params += "&direction=asc"  # first older pull request

    # prs_count = getPullRequests(url_pulls+url_params)
    issues_prs_count = getIssuesPullRequests(url_issues+url_params)

    usersToES(users)  # cache users in ES
    geoLocationsToES(geolocations)

    # logging.info("Total Pull Requests " + str(prs_count))
    logging.info("Total Issues Pull Requests " + str(issues_prs_count))