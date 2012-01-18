# Copyright (c) 2006-2010, Jesse Liesch
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the author nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" 
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE 
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE IMPLIED
# DISCLAIMED. IN NO EVENT SHALL JESSE LIESCH BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from jsonrpc import ServiceProxy
from db import *
import os
import datetime
import prefs
import zlib
import binascii

import appGlobal
from transaction import *

class StockData:
	def __init__(self):
		self.s = ServiceProxy("http://www.icarra2.com/cgi-bin/webApi.py")
		
		self.db = Db(os.path.join(prefs.Prefs.prefsRootPath(), "stocks.db"))
		# TODO: make unique index on ticker
		self.db.checkTable("stockData", [
			{"name": "ticker", "type": "text"},
			{"name": "date", "type": "datetime"},
			{"name": "open", "type": "float default 0.0"},
			{"name": "high", "type": "float default 0.0"},
			{"name": "low", "type": "float default 0.0"},
			{"name": "close", "type": "float default 0.0"},
			{"name": "volume", "type": "float default 0"}], index = [
			{"name": "tickerDate", "cols": ["ticker", "date"]}])
		
		self.db.checkTable("stockDividends", [
			{"name": "ticker", "type": "text"},
			{"name": "date", "type": "datetime"},
			{"name": "value", "type": "float"}], index = [
			{"name": "tickerDate", "cols": ["ticker", "date"]}])

		self.db.checkTable("stockSplits", [
			{"name": "ticker", "type": "text"},
			{"name": "date", "type": "datetime"},
			{"name": "value", "type": "float"}], index = [
			{"name": "tickerDate", "cols": ["ticker", "date"]}])

		self.db.checkTable("stockInfo", [
			{"name": "ticker", "type": "text"},
			{"name": "lastDownload", "type": "datetime"},
			{"name": "icarraTicker", "type": "text"},
			{"name": "name", "type": "text"}], unique = [
			{"name": "ticker", "cols": ["ticker"]}])

		self.db.checkTable("stockNews", [
			{"name": "ticker", "type": "text"},
			{"name": "date", "type": "datetime"},
			{"name": "title", "type": "text"},
			{"name": "summary", "type": "text"},
			{"name": "rating", "type": "int"},
			{"name": "url", "type": "text"},
			{"name": "downloaded", "type": "bool default 0"},
			{"name": "content", "type": "text"}], index = [
			{"name": "tickerDate", "cols": ["ticker", "date"]}])

		self.stocks = {}
	
	def updateStocks(self, tickers, status = False):
		'''Return True if new data is received'''
		if status:
			status.setStatus("Building Stock Data Query", 20)

		if not tickers:
			if status:
				status.setStatus("Finished Downloading Stock Data (no stocks)", 100)
			return
		
		# Only allow one download at a time
		appGlobal.getApp().beginBigTask('downloading stock data', status)

		try:
			update = {}
			for t in tickers:
				if t == "__CASH__":
					continue
				self.setLastDownload(t)
				
				last = self.getLastDate(t)
				if last:
					update[t] = last
				else:
					update[t] = datetime.datetime(1900, 1, 1)
	
			if status:
				status.setStatus("Querying server", 40)
			gotData = self.getFromServer(update, status)
			if status:
				status.setStatus("Finished Downloading Stock Data", 100)
			
			appGlobal.getApp().endBigTask()
		except:
			# End big task, re-raise exception
			appGlobal.getApp().endBigTask()
			raise

		return gotData
	
	def updatePortfolioStocks(self, portfolio, status = False):
		'''Downloading new data for every ticker in the portfolio.
		Only applies to stocks that have not been downloaded in 4 hours.
		Return True if new data is received.'''
		
		update = {}
		for ticker in portfolio.getTickers(includeAllocation = True):
			if ticker.startswith("__") and ticker.endswith("__"):
				continue
			last = self.getLastDownload(ticker)
			
			# Include if never updated
			if last is False:
				update[ticker] = datetime.datetime(1900, 1, 1)
				self.setLastDownload(ticker)
			elif datetime.datetime.now() - last > datetime.timedelta(hours = 4):
				# Append if downloaded in less than 4 hours
				update[ticker] = last
				self.setLastDownload(ticker)

		if update:
			if status:
				status.setStatus("Querying server")
			return self.getFromServer(update, status)

		return False

	def suggest(self, ticker):
		try:
			request = {"ticker": str(ticker)}
			return self.s.suggest(request)
		except Exception, e:
			appGlobal.setFailConnected(True)
			return False

	def getFromServer(self, request, status = False):
		'''Return True if new stock data is received'''
		
		if appGlobal.getFailConnected():
			return False
		
		# Encode as string
		icarraTickers = {}
		for (ticker, date) in request.items():
			icarraTicker = self.getIcarraTicker(ticker)
			icarraTickers[icarraTicker] = ticker
			
			# Change request to icarraTicker if necessary
			if icarraTicker != ticker:
				request[icarraTicker] = date.strftime("%Y-%m-%d %H:%M:%S")
				del request[ticker]
			else:
				request[ticker] = date.strftime("%Y-%m-%d %H:%M:%S")
		request["__UNIQUEID__"] = str(appGlobal.getApp().getUniqueId())

		try:
			if status:
				status.setStatus("Receiving Stock Data", 70)
			data = self.s.getStockZip(request)
		except Exception, inst:
			appGlobal.setFailConnected(True)
			return False
		
		# Try decompressing
		# Ignore errors (assume not compressed)
		try:
			unencoded = binascii.a2b_base64(data)
			uncompressed = zlib.decompress(unencoded)
			data = uncompressed
		except Exception, inst:
			pass
		
		if status:
			status.setStatus("Updating Stock Database", 80)
		self.db.beginTransaction()
		gotData = False
		for line in data.split("\n"):
			#print line
			values = line.split(",")
			if len(values) < 4:
				continue
			
			if values[0] == "#vers" and len(values) == 4:
				appGlobal.getApp().prefs.updateLatestVersion(int(values[1]), int(values[2]), int(values[3]))
			if values[0] == "stock" and len(values) == 8:
				on = {
					"ticker": icarraTickers[values[1].upper()],
					"date": values[2]
					}
				if self.db.insertOrUpdate("stockData", {
					"ticker": icarraTickers[values[1].upper()],
					"date": values[2],
					"open": values[3],
					"high": values[4],
					"low": values[5],
					"close": values[6],
					"volume": values[7]},
					on):
					gotData = True
			elif values[0] == "dividend" and len(values) == 4:
				if self.db.insertOrUpdate("stockDividends", {
					"ticker": icarraTickers[values[1].upper()],
					"date": values[2],
					"value": values[3]}):
					gotData = True
			elif values[0] == "split" and len(values) == 4:
				if self.db.insertOrUpdate("stockSplits", {
					"ticker": icarraTickers[values[1].upper()],
					"date": values[2],
					"value": values[3]}):
					gotData = True
		self.db.commitTransaction()
		
		return gotData
	
	def readTickerFromDb(self, ticker):
		res = self.db.select("stockData", where = {"ticker": ticker}, orderBy = "date")
		
		self.stocks[ticker] = []
		for row in res.fetchall():
			self.stocks[ticker].append({
				"date": row["date"],
				"open": row["open"],
				"high": row["high"],
				"low": row["low"],
				"close": row["close"],
				"volume": row["volume"]})
	
	def readFromDb(self):
		self.stocks = {}
		res = self.db.select("stockData", orderBy = "ticker, date asc")
		
		lastTicker = ""
		for row in res.fetchall():
			ticker = row["ticker"].upper()
			if ticker != lastTicker:
				self.stocks[ticker] = []
			self.stocks[ticker].append({
				"date": row["date"],
				"open": row["open"],
				"high": row["high"],
				"low": row["low"],
				"close": row["close"],
				"volume": row["volume"]})
			lastTicker = ticker
		
	def getIcarraTicker(self, ticker):
		res = self.db.select("stockInfo", where = {"ticker": ticker.upper()})
		row = res.fetchone()
		
		if not row:
			return ticker
		else:
			icarraTicker = row["icarraTicker"]
			if icarraTicker == None or icarraTicker == "":
				return ticker.upper()
			else:
				return icarraTicker.upper()
	
	def setIcarraTicker(self, ticker, icarraTicker):
		data = {"ticker": ticker, "icarraTicker": icarraTicker.upper()}
		where = {"ticker": ticker}
		self.db.update("stockInfo", data = data, where = where)
	
	def checkEmptyName(self, ticker, name):
		data = {"ticker": ticker, "name": name}
		where = {"ticker": ticker, "name": "is null"}
		self.db.update("stockInfo", data = data, where = where)

	def getName(self, ticker):
		where = {"ticker": ticker}
		res = self.db.select("stockInfo", where = where)
		row = res.fetchone()
		if not row:
			return False
		else:
			return row["name"]
	
	def getLastDownload(self, ticker):
		res = self.db.select("stockInfo", where = {"ticker": ticker.upper()})
		row = res.fetchone()
		
		if not row:
			return False
		else:
			if row["lastDownload"] == None or row["lastDownload"] == "":
				return False
			else:
				return Transaction.parseDate(row["lastDownload"])
	
	def setLastDownload(self, ticker):
		last = datetime.datetime.now()
		data = {"ticker": ticker, "lastDownload": last.strftime("%Y-%m-%d %H:%M:%S")}
		on = {"ticker": ticker}
		self.db.insertOrUpdate("stockInfo", data = data, on = on)
		
	def getTickers(self):
		cursor = self.db.query("select distinct(ticker) as ticker from stockInfo")

		ret = []
		for row in cursor.fetchall():
			ret.append(row["ticker"])
		
		return ret

	def getPrice(self, ticker, date):
		where = {"ticker": ticker.upper(), "date": date.strftime("%Y-%m-%d 00:00:00")}
		res = self.db.select("stockData", where = where)
		row = res.fetchone()
		if not row:
			return False

		return {
			"date": Transaction.parseDate(row["date"]),
			"open": float(row["open"]),
			"high": float(row["high"]),
			"low": float(row["low"]),
			"close": float(row["close"]),
			"volume": float(row["volume"])}
	
	def getOptionPrice(self, ticker, expire, strike, date, type):
		# This function is currently a placeholder until Icarra supports option prices
		# This function reads option prices from the portfolio transactions
		# Extract first token (incase ticker is "VIX Feb-11 $xxx")
		if ticker.find(" ") != -1:
			ticker = ticker[:ticker.find(" ")]
		transactions = appGlobal.getApp().portfolio.getTransactions(ticker, ascending = True)
		price = False
		for t in transactions:
			if not t.type in [Transaction.buyToOpen, Transaction.buyToClose, Transaction.sellToOpen, Transaction.sellToClose] or t.ticker != ticker or t.optionExpire != expire or t.optionStrike != strike or t.subType != type:
				continue
			if t.date > date:
				break
			price = t.pricePerShare
		return price

	def getNearestPrice(self, ticker, date):
		'''Return price closest to date.  Checks within +/- 7 days.'''
		for d in [0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7]:
			where = {"ticker": ticker.upper(), "date": (date + datetime.timedelta(days = d)).strftime("%Y-%m-%d 00:00:00")}
			res = self.db.select("stockData", where = where)
			row = res.fetchone()
			if row:
				return {
					"date": Transaction.parseDate(row["date"]),
					"open": float(row["open"]),
					"high": float(row["high"]),
					"low": float(row["low"]),
					"close": float(row["close"]),
					"volume": float(row["volume"])}
		
		return False

	def getDividend(self, ticker, date):
		where = {"ticker": ticker.upper(), "date": date.strftime("%Y-%m-%d 00:00:00")}
		res = self.db.select("stockDividends", where = where)
		
		row = res.fetchone()
		if not row:
			return False

		return {
			"date": Transaction.parseDate(row["date"]),
			"value": float(row["value"])}

	def getDividends(self, ticker, firstDate = False, desc = False):
		where = {"ticker": ticker.upper()}
		if firstDate:
			where["date >="] = firstDate.strftime("%Y-%m-%d 00:00:00")
		cursor = self.db.select("stockDividends", where = where, orderBy = "date asc")
		
		res = []
		for row in cursor.fetchall():
			res.append({
				"date": Transaction.parseDate(row["date"]),
				"value": float(row["value"])})
		
		if desc:
			res.reverse()
		
		return res

	def getSplits(self, ticker, firstDate = False, lastDate = False, desc = False):
		where = {"ticker": ticker.upper()}
		if firstDate:
			where["date >="] = firstDate.strftime("%Y-%m-%d 00:00:00")
		cursor = self.db.select("stockSplits", where = where, orderBy = "date asc")
		
		res = []
		for row in cursor.fetchall():
			res.append({
				"date": Transaction.parseDate(row["date"]),
				"value": float(row["value"])})
		
		if desc:
			res.reverse()
		
		return res

	def getPrices(self, ticker, endDate = False, startDate = False, desc = False, limit = False, splitAdjusted = False):
		where = {"ticker": ticker.upper()}
		order = "ticker, date asc"
		if startDate:
			where["date >="] = datetime.datetime(startDate.year, startDate.month, startDate.day, 0, 0, 0)
		if endDate:
			where["date <="] = datetime.datetime(endDate.year, endDate.month, endDate.day, 23, 59, 59)
		res = self.db.select("stockData", where = where, orderBy = order, limit = limit)
		
		ret = []
		for row in res.fetchall():
			ticker = row["ticker"].upper()
			ret.append({
				"date": Transaction.parseDate(row["date"]),
				"open": float(row["open"]),
				"high": float(row["high"]),
				"low": float(row["low"]),
				"close": float(row["close"]),
				"volume": float(row["volume"])})
		
		if splitAdjusted:
			splitFactor = 1
			splits = self.getSplits(ticker, firstDate = startDate, lastDate = endDate)
			pi = 0
			si = 0
			while pi < len(ret):
				if si < len(splits):
					if splits[si]['date'] <= ret[pi]['date']:
						splitFactor *= splits[si]['value']
						si += 1
				
				if splitFactor != 1:
					ret[pi]['high'] = ret[pi]['high'] * splitFactor
					ret[pi]['low'] = ret[pi]['low'] * splitFactor
					ret[pi]['open'] = ret[pi]['open'] * splitFactor
					ret[pi]['close'] = ret[pi]['close'] * splitFactor
				pi += 1

		if desc:
			ret.reverse()

		return ret

	def getLastDate(self, ticker):
		res = self.db.select("stockData", where = {"ticker": ticker.upper()}, orderBy = "date desc", limit = 1)
		row = res.fetchone()
		if not row:
			return False
		else:
			return Transaction.parseDate(row["date"])

	def getFirstDate(self, ticker):
		res = self.db.select("stockData", where = {"ticker": ticker.upper()}, orderBy = "date asc", limit = 1)
		row = res.fetchone()
		if not row:
			return False
		else:
			return Transaction.parseDate(row["date"])
		
	def addNews(self, ticker, date, title, summary, url):
		data = {
			"ticker": ticker,
			"date": date,
			"title": title,
			"summary": summary,
			"url": url,
		}
		on = {
			"ticker": ticker,
			"date": date,
			"url": url
		}

		self.db.insertOrUpdate("stockNews", data, on)
	
	def setNewsRating(self, ticker, date, url, rating):
		where = {
			"ticker": ticker,
			"date": date.strftime("%Y-%m-%d %H:%M:%S"),
			"url": url
		}
		self.db.update("stockNews", {"rating": rating}, where)
		
	def getNews(self, ticker = False):
		where = {}
		if ticker:
			where["ticker"] = ticker
		
		ret = []
		res = self.db.select("stockNews", orderBy = "date desc", where = where)
		for row in res.fetchall():
			row["date"] = Transaction.parseDate(row["date"])
			ret.append(row)
		
		return ret

if __name__ == "__main__":
	s = StockData()
	s.getFromServer("agg")
	s.readFromDb()
