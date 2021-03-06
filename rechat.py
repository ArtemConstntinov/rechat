#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import logging
import tornado.escape
from tornado.ioloop import IOLoop
import tornado.web
import os.path
import rethinkdb as r
from tornado import httpserver
from time import time
# from tornado.concurrent import Future
from tornado import gen
from tornado.options import define, options, parse_command_line

define("port", default=8888, help="run on the given port", type=int)
define("debug", default=True, help="run in debug mode")


def setup_db(db_name="rechat", tables=['events']):
    connection = r.connect(host="localhost")
    try:
        r.db_create(db_name).run(connection)
        for tbl in tables:
            r.db(db_name).table_create(tbl, durability="hard").run(connection)
        logging.info('Database setup completed.')
    except r.RqlRuntimeError:
        logging.warn('Database/Table already exists.')
    finally:
        connection.close()


class RechatApp(tornado.web.Application):

    def __init__(self, db):

        handlers = [
            (r"/", MainHandler),
            (r"/a/message/new", MessageNewHandler),
            (r"/a/message/updates", MessageUpdatesHandler),
        ]

        settings = dict(cookie_secret="_asdfasdaasdfasfas",
                        template_path=os.path.join(
                            os.path.dirname(__file__), "templates"),
                        static_path=os.path.join(
                            os.path.dirname(__file__), "static"),
                        xsrf_cookies=True,
                        debug=options.debug)
        self.db = db
        logging.info(db)
        tornado.web.Application.__init__(self, handlers, **settings)


class BaseHandler(tornado.web.RequestHandler):

    def initialize(self):
        self.db = self.application.db
        self.evt = r.table("events")


class MainHandler(BaseHandler):

    @gen.coroutine
    def get(self):
        curs = yield self.evt.run(self.db)
        messages = []
        while (yield curs.fetch_next()):
            item = yield curs.next()
            messages.append(item)

        self.render("index.html", messages=messages)


class MessageNewHandler(BaseHandler):

    @gen.coroutine
    def post(self):
        message = {
            "body": self.get_argument("body")
        }
        # to_basestring is necessary for Python 3's json encoder,
        # which doesn't accept byte strings.
        start = time()
        messages = (yield self.evt.insert(message).run(self.db))
        time_taken = time() - start
        logging.warn("DBINSERT: %s seconds" % time_taken)
        message['id'] = messages['generated_keys'][0]
        message["html"] = tornado.escape.to_basestring(
            self.render_string("message.html", message=message))
        if self.get_argument("next", None):
            self.redirect(self.get_argument("next"))
        else:
            self.write(message)


class MessageUpdatesHandler(BaseHandler):

    @gen.coroutine
    def post(self):
        curs = yield self.evt.changes().run(self.db)

        while (yield curs.fetch_next()):
            feed = yield curs.next()
            message = {
                'id': feed['new_val']['id'],
                'html': tornado.escape.to_basestring(
                    self.render_string("message.html",
                                       message=feed['new_val']))}
            break

        self.finish(dict(messages=[message]))


@gen.coroutine
def main():
    """ Async main method. It needed to be async due to r.connect is async . """
    parse_command_line()
    db_name = "rechat"
    setup_db(db_name)
    r.set_loop_type("tornado")

    db = yield r.connect("localhost", db=db_name)
    #Single db connection for everything thanks a lot Ben and Jeese
    http_server = httpserver.HTTPServer(RechatApp(db))
    http_server.listen(options.port)

if __name__ == "__main__":
    IOLoop.current().run_sync(main)
    IOLoop.current().start()
