import copy
import json
from typing import Tuple, Union, List, Any

import psycopg2
import urllib3

from opensearchpy import helpers as opensearch_helpers
from opensearchpy.exceptions import OpenSearchException
from tenacity import *

from ..util.airflow import get_postgres_conn
from ..util.log import logger
from ..base_dict.opensearch_index import OPENSEARCH_INDEX_GITHUB_COMMITS, OPENSEARCH_INDEX_GITHUB_ISSUES


class OpenSearchAPIException(Exception):
    def __init__(self, message, status):
        super().__init__(message, status)
        self.message = message
        self.status = status


class OpensearchAPI:
    def bulk_github_commits(self, opensearch_client, github_commits, owner, repo) -> Tuple[int, int]:
        bulk_all_github_commits = []
        for now_commit in github_commits:
            has_commit = opensearch_client.search(index=OPENSEARCH_INDEX_GITHUB_COMMITS,
                                                  body={
                                                      "query": {
                                                          "term": {
                                                              "raw_data.sha.keyword": {
                                                                  "value": now_commit["sha"]
                                                              }
                                                          }
                                                      }
                                                  }
                                                  )
            if len(has_commit["hits"]["hits"]) == 0:
                template = {"_index": OPENSEARCH_INDEX_GITHUB_COMMITS,
                            "_source": {"search_key": {"owner": owner, "repo": repo},
                                        "raw_data": None}}
                commit_item = copy.deepcopy(template)
                commit_item["_source"]["raw_data"] = now_commit
                bulk_all_github_commits.append(commit_item)

        if len(bulk_all_github_commits) > 0:
            success, failed = self.do_opensearch_bulk(opensearch_client, bulk_all_github_commits, owner, repo)
            logger.info(
                f"current github commits page insert count：{len(bulk_all_github_commits)},success:{success},failed:{failed}")
            return success, failed
        else:
            return 0, 0

    def bulk_github_issues(self, opensearch_client, github_issues, owner, repo):
        bulk_all_github_issues = []

        for now_issue in github_issues:
            # 如果对应 issue number存在则先删除
            del_result = opensearch_client.delete_by_query(index=OPENSEARCH_INDEX_GITHUB_ISSUES,
                                                           body={
                                                               "track_total_hits": True,
                                                               "query": {
                                                                   "bool": {
                                                                       "must": [
                                                                           {
                                                                               "term": {
                                                                                   "raw_data.number": {
                                                                                       "value": now_issue["number"]
                                                                                   }
                                                                               }
                                                                           },
                                                                           {
                                                                               "term": {
                                                                                   "search_key.owner.keyword": {
                                                                                       "value": owner
                                                                                   }
                                                                               }
                                                                           },
                                                                           {
                                                                               "term": {
                                                                                   "search_key.repo.keyword": {
                                                                                       "value": repo
                                                                                   }
                                                                               }
                                                                           }
                                                                       ]
                                                                   }
                                                               }
                                                           })
            logger.info(f"DELETE github issues result:{del_result}")

            template = {"_index": OPENSEARCH_INDEX_GITHUB_ISSUES,
                        "_source": {"search_key": {"owner": owner, "repo": repo},
                                    "raw_data": None}}
            commit_item = copy.deepcopy(template)
            commit_item["_source"]["raw_data"] = now_issue
            bulk_all_github_issues.append(commit_item)
            logger.info(f"add sync github issues number:{now_issue['number']}")

        success, failed = opensearch_helpers.bulk(client=opensearch_client, actions=bulk_all_github_issues)
        logger.info(f"now page:{len(bulk_all_github_issues)} sync github issues success:{success} & failed:{failed}")

        return success, failed

    def do_opensearch_bulk_error_callback(retry_state):
        postgres_conn = get_postgres_conn()
        sql = '''INSERT INTO retry_data(
                    owner, repo, type, data) 
                    VALUES (%s, %s, %s, %s);'''
        try:
            cur = postgres_conn.cursor()
            owner = retry_state.args[2]
            repo = retry_state.args[3]
            for bulk_item in retry_state.args[1]:
                cur.execute(sql, (owner, repo, 'opensearch_bulk', json.dumps(bulk_item)))
            postgres_conn.commit()
            cur.close()
        except (psycopg2.DatabaseError) as error:
            logger.error(f"psycopg2.DatabaseError:{error}")

        finally:
            if postgres_conn is not None:
                postgres_conn.close()

        return retry_state.outcome.result()

    # retry 防止OpenSearchException
    @retry(stop=stop_after_attempt(3),
           wait=wait_fixed(1),
           retry_error_callback=do_opensearch_bulk_error_callback,
           retry=(retry_if_exception_type(OSError) | retry_if_exception_type(
               urllib3.exceptions.HTTPError) | retry_if_exception_type(OpenSearchException))
           )
    def do_opensearch_bulk(self, opensearch_client, bulk_all_data, owner, repo):
        logger.info(f"owner:{owner},repo:{repo}::do_opensearch_bulk")

        success, failed = opensearch_helpers.bulk(client=opensearch_client, actions=bulk_all_data)
        # 强制抛出异常
        # raise OpenSearchException("do_opensearch_bulk Error")
        return success, failed