from brokerage import *

class Brokerage(BrokerageBase):
	def getName(self):
		return "OptionsXpress"
	
	def getUrl(self):
		return "https://ofx.optionsxpress.com/cgi-bin/ox.exe"
	
	def getOrg(self):
		return "10876"
	
	def getFid(self):
		return "10876"
	
	def getBrokerId(self):
		return "optionxpress.com"
	
	def getNotes(self):
		return ["Short sales may be imported as regular sell transactions", "Mutual fund purchases may show up as dividend reinvestments", "Other transaction types may be mis-labeled"]
	
	def massageStockInfo(self, stockInfo):
		# Use ticker first, then secname if ticker is not found
		if "ticker" in stockInfo:
			ticker = stockInfo["ticker"]
		else:
			return
		
		# Special treatment for options
		if "opttype" in stockInfo:
			# If dtexpire is 19000101 then ticker is TICKER^^YYMMDDgarbage
			if "dtexpire" in stockInfo and stockInfo["dtexpire"] == "19000101":
				carats = ticker.find("^^")
				if carats != -1:
					yy = int(ticker[carats + 2:carats + 4])
					mm = int(ticker[carats + 4:carats + 6])
					dd = int(ticker[carats + 6:carats + 8])
					if yy < 70:
						yy += 2000
					else:
						yy += 1900
					stockInfo["dtexpire"] = "%04d%02d%02d" % (yy, mm, dd)
			
			# Opttype may be incorrect, some calls are mislabeled as puts
			if "secname" in stockInfo and stockInfo["secname"].lower().endswith("call"):
				stockInfo["opttype"] = "CALL"
			
			# If ticker looks like ABC^^ZZZZ then remove ^^ and everything after
			if ticker.find("^^") != -1:
				stockInfo["ticker"] = ticker[0:ticker.find("^^")]
			# OptionsXpress may provide a ticker like .XYZ when the real ticker is the first character in the memo
			if ticker.startswith(".") and len(stockInfo["memo"]) > 0:
				stockInfo["ticker"] = stockInfo["memo"].split(" ")[0]

	def preParseTransaction(self, trans):
		retTrans = False
		
		# Ignore sellmf with 0.00 units and 0.00 unitprice
		if trans.keyEqual("type", "sellmf") and trans.keyEqual("units", "0.00") and trans.keyEqual("unitprice", "0.00"):
			trans["type"] = "ignore"

		if trans.keyEqual("optselltype", "selltoopen") or trans.keyEqual("optselltype", "selltoclose"):
			# Option transactions have an incorrect unitprice
			if trans.getKey("units") != "0.00":
				trans["unitprice"] = str((float(trans.getKey("total")) + float(trans.getKey("commission")) + float(trans.getKey("taxes")) + float(trans.getKey("fees"))) / abs(float(trans.getKey("units"))))
		elif trans.keyEqual("optbuytype", "buytoopen") or trans.keyEqual("optbuytype", "buytoclose"):
			# Option transactions have an incorrect unitprice
			if trans.getKey("units") != "0.00":
				trans["unitprice"] = str((abs(float(trans.getKey("total"))) - float(trans.getKey("commission")) - float(trans.getKey("taxes")) - float(trans.getKey("fees"))) / abs(float(trans.getKey("units"))))

	def postProcessTransactions(self, transactions):
		# Assign, exercised and expired options are always listed as buyToClose and sellToClose.  Keep track of last
		# buy/sell transaction to make a guess
		for t in transactions:
			if t.type != Transaction.buyToClose and t.type != Transaction.sellToClose:
				continue
			if t.pricePerShare or t.total:
				continue
			
			# This should be an assigned, exercised or expired transaction.
			# Loop over all transactions searching for a buy/sell transaction
			buys = 0
			sells = 0
			for t2 in transactions:
				if t2.ticker == t.ticker and t2.date == t.date and abs(t2.pricePerShare - t.optionStrike) < 1.0e-6:
					if t2.type == Transaction.buy:
						buys += t2.getShares()
					elif t2.type == Transaction.sell:
						sells += t2.getShares()
			
			if t.type == Transaction.sellToClose and t.subType == Transaction.optionPut and sells >= t.getShares() * 100:
				# Handle sell to close of put (sell stock)
				t.type = Transaction.exercise
			elif t.type == Transaction.sellToClose and t.subType == Transaction.optionCall and buys >= t.getShares() * 100:
				# Handle sell to close of call (buy stock)
				t.type = Transaction.exercise
			else:
				t.type = Transaction.expire
		
		# buy with 0 pricePerShare and 0 total is a dividend reinvest if there is a corresponding sell with 0.00 units
		# buy with 0 pricePerShare and 0 total is a transfer in
		for t in transactions:
			if not (t.type == Transaction.buy and t.pricePerShare == 0):
				continue
			
			# Search for sell with 0 shares
			found = False
			for t2 in transactions:
				if t2.ticker == t.ticker and (t2.date - t.date < datetime.timedelta(days = 1)) and t2.type == Transaction.sell:
					t.type = Transaction.dividendReinvest
					t.pricePerShare = t2.pricePerShare
					t.total = t2.total
					transactions.remove(t2)
					found = True
					break
			
			if not found:
				t.type = Transaction.transferIn
		
		# Combine buy and dividend transactions into dividendReinvest transactions
		# Also delete the corresponding sell of 0 shares
		# Loop over a copy of the list since we will delete from it
		for t in transactions[:]:
			if t.type != Transaction.dividend:
				continue
			
			for t2 in transactions:
				if t2.ticker == t.ticker and (t2.date - t.date < datetime.timedelta(days = 1)) and t2.type == Transaction.sell and t2.shares == 0:
					transactions.remove(t2)
					break
			
			for t2 in transactions:
				if t2.ticker == t.ticker and (t2.date - t.date < datetime.timedelta(days = 1)) and t2.type == Transaction.buy and t2.total == t.total:
					t2.type = Transaction.dividendReinvest
					transactions.remove(t)
					break
