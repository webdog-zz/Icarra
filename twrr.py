from basis import *

class Twrr:
	"""Implements time weighted returns.  Relies on a basis tracker for shorts/covers."""

	def __init__(self):
		self.day = 0
		self.ticker = False
		# Shares is a count of shares owned per ticker
		self.shares = {}
		self.sharesShort = {}
		self.prices = {}
		self.yesterdayPrices = {}
		self.basis = Basis()
		self.adjustBasises = {}
		self.adjustment = 0
		self.totalAdjustment = 0
		# Last positive value
		self.lastValue = False 
		self.lastReturn = 1.0
		self.yesterdayValue = False
		self.stockDividend = {}
		self.dividendMod = 1.0
		self.feeMod = 1.0

	def beginTransactions(self):
		# cashIn and sharesIn are keyed by ticker
		self.cashIn = {}
		self.sharesIn = {}
		self.cashOut = {}
		self.sharesOut = {}
		self.cashInShort = {}
		self.sharesInShort = {}
		self.cashOutShort = {}
		self.sharesOutShort = {}
		self.dividends = 0.0
		self.fees = 0.0
		self.adjustment = 0
	
	def endTransactions(self):
		self.day += 1
		
		# Algorithm:
		# Twrr(1) = 1
		# Twrr(n) = Twrr(n-1) * Performance(n-1)
		
		# Compute cashIn
		todayNetCashIn = 0.0
		todayCashIn = 0.0
		todayCashOut = 0.0
		for t in self.cashIn:
			todayNetCashIn += abs(self.cashIn[t])
			todayCashIn += abs(self.cashIn[t])
		for t in self.cashOut:
			todayNetCashIn -= abs(self.cashOut[t])
			todayCashOut += abs(self.cashOut[t])
		for t in self.cashInShort:
			todayNetCashIn += abs(self.cashInShort[t])
			todayCashIn += abs(self.cashInShort[t])
		for t in self.cashOutShort:
			todayNetCashIn -= abs(self.cashOutShort[t])
			todayCashOut += abs(self.cashOutShort[t])
		
		# Handle splits
		'''for t in self.sharesIn.keys():
			if self.cashIn[t] == 0:
				# Long split N-1
				if not t in self.shares:
					self.shares[t] = 0
				self.shares[t] += self.sharesIn[t]
				del self.sharesIn[t]
				del self.cashIn[t]
		for t in self.sharesOut.keys():
			if self.cashOut[t] == 0:
				# Long split 1-N
				if not t in self.shares:
					self.shares[t] = 0
				self.shares[t] -= self.sharesOut[t]
				del self.sharesOut[t]
				del self.cashOut[t]'''
		for t in self.stockDividend:
			if not t in self.shares:
				self.shares[t] = 0.0
			self.shares[t] += self.stockDividend[t]
		self.stockDividend = {}
		
		# Compute yesterday's holdings at today's prices
		todaysStartValue = self.getTotalValue()
		
		# List of returns.  Each value is a tuple of (dollar amount, return)
		returnsToday = []
		
		# Adjust basis
		for t in self.adjustBasises:
			basisValue = self.shares[t] * self.prices[t]
			basisValue = self.basis.getBasis(t)
			if basisValue == 0:
				raise Exception("adjust basis but not value for %s" % t)

			if todaysStartValue > 0:
				self.lastReturn *= (todaysStartValue + self.adjustBasises[t]) / todaysStartValue
			#todo adjust basis
		self.adjustBasises = {}

		# Now add shares
		#if self.sharesIn or self.sharesOut:
		#	print self.day, "sharesIn", self.sharesIn, "sharesOut", self.sharesOut
		for t in self.sharesIn:
			if self.sharesIn[t] != 0:
				thisPrice = self.cashIn[t] / self.sharesIn[t]
				self.basis.add(t, self.day, self.sharesIn[t], thisPrice)
				
				if self.prices[t] != 0 and thisPrice != 0:
					returnsToday.append((self.cashIn[t], self.prices[t] / thisPrice))
				else:
					returnsToday.append((self.cashIn[t], 1.0))

			if not t in self.shares:
				self.shares[t] = 0
			self.shares[t] += self.sharesIn[t]
		self.cashIn = {}
		self.sharesIn = {}
		
		# Now add shares (short)
		#if self.sharesInShort or self.sharesOutShort:
		#	print self.day, "sharesInShort", self.sharesInShort, "sharesOutShort", self.sharesOutShort
		for t in self.sharesInShort:
			if self.sharesInShort[t] != 0:
				# Short
				thisPrice = self.cashInShort[t] / self.sharesInShort[t]
				self.basis.add(t, self.day, self.sharesInShort[t], thisPrice)
				
				# Calculate return from these shares
				if thisPrice < self.prices[t]:
					# Loss
					thisReturn = thisPrice / self.prices[t]
				else:
					# Gain or same price
					# 10 -> 9 = 1.1 = 1 + (10 - 9) / 10
					thisReturn = 1.0 + (self.prices[t] - thisPrice) / self.prices[t]
				returnsToday.append((self.cashInShort[t], thisReturn))
			if not t in self.sharesShort:
				self.sharesShort[t] = 0
			self.sharesShort[t] += self.sharesInShort[t]
		self.cashInShort = {}
		self.sharesInShort = {}

		# Now remove shares
		for t in self.sharesOut:
			if self.sharesOut[t] != 0:
				thisPrice = self.cashOut[t] / self.sharesOut[t]
				if self.cashOut[t] == 0:
					cashOut = self.basis.getBasis(t)
				else:
					cashOut = self.cashOut[t]
				
				if t in self.yesterdayPrices and self.yesterdayPrices[t] != 0:
					returnsToday.append((cashOut, thisPrice / self.yesterdayPrices[t]))
				elif self.prices[t] != 0:
					returnsToday.append((cashOut, thisPrice / self.prices[t]))
				else:
					returnsToday.append((cashOut, 1.0))
				#print returnsToday

			self.basis.remove(t, abs(self.sharesOut[t]))

			if not t in self.shares:
				self.shares[t] = 0
			self.shares[t] -= self.sharesOut[t]
		self.cashOut = {}
		self.sharesOut = {}

		# Now remove shares (short)
		for t in self.sharesOutShort:
			if self.sharesOutShort[t] != 0:
				salePrice = self.cashOutShort[t] / self.sharesOutShort[t]
				todayPrice = False
				if t in self.yesterdayPrices and self.yesterdayPrices[t] != 0:
					yesterdayPrice = self.yesterdayPrices[t]
				else:
					yesterdayPrice = self.prices[t]
				
				# Return = today's value / yesterday's value
				basis = self.basis.getBasis(t)
				yesterdayValue = self.shortValue(self.sharesOutShort[t], basis, yesterdayPrice, basis * self.sharesOutShort[t])
				todayValue = self.shortValue(self.sharesOutShort[t], basis, self.prices[t], basis * self.sharesOutShort[t])
				
				if yesterdayValue and todayValue:
					returnsToday.append((basis, todayValue / yesterdayValue))

			self.basis.remove(t, self.sharesOutShort[t])

			if not t in self.sharesShort:
				self.sharesShort[t] = 0
			self.sharesShort[t] -= self.sharesOutShort[t]
			if abs(self.sharesShort[t]) < 1.0e-6:
				del self.sharesShort[t]
		self.cashOutShort = {}
		self.sharesOutShort = {}

		# Compute today's value
		todaysValue = self.getTotalValue()
		
		# Update returns
		#print self.day, "ydayValue", self.yesterdayValue, "tdaysStartValue", todaysStartValue, "tdayNetCashIn", todayNetCashIn, "tdaysValue", todaysValue
		if not self.yesterdayValue and todayNetCashIn != 0:
			# First holdings or a re-opened position
			#print self.day, "cashIn", todayCashIn, "cashOut", todayCashOut, "netCashIn", todayNetCashIn
			#self.lastReturn *= (todaysValue + todayCashOut) / todayCashIn
			pass
		elif todaysStartValue and self.yesterdayValue:
			# Returns from current holdings
			returnsToday.append((todaysValue, todaysStartValue / self.yesterdayValue))
		elif not todaysValue and self.yesterdayValue:
			# Remove all shares
			if todayNetCashIn < 0:
				#self.lastReturn *= -todayNetCashIn / self.yesterdayValue
				returnsToday.append(-todayNetCashIn, -todayNetCashIn / self.yesterdayValue)
		
		# Now compute returns
		# Weight returns by underlying cash value
		num = 0.0
		den = 0.0
		for ret in returnsToday:
			(thisAmount, thisReturn) = ret
			num += thisAmount * thisReturn
			den += thisAmount
		if den > 0:
			#if len(returnsToday) > 1:
			#	print returnsToday, "=", num / den, "yesterday", self.lastReturn
			self.lastReturn *= num / den
		
		# Check for adjustment on first day
		if not self.yesterdayValue and self.adjustment:
			withoutAdjustment = todaysValue - self.adjustment
			self.lastReturn *= (withoutAdjustment + self.adjustment) / withoutAdjustment
		
		# Update fees based on largest holdings of yesterday, today, or cashIn
		if self.fees:
			maxHoldings = max(todaysStartValue, todaysValue, todayNetCashIn)
			if maxHoldings > 0:
				# Account for dividends and fees
				if self.dividends > self.fees:
					maxHoldings += self.dividends - self.fees

				if self.ticker == "__CASH__":
					if maxHoldings < self.fees:
						self.feeMod = 0.0
					else:
						self.feeMod *= (maxHoldings - self.fees) / maxHoldings
				else:
					self.feeMod *= maxHoldings / (maxHoldings + self.fees)
			else:
				self.feeMod = 0.0
			#print self.day, "fees", self.fees, "holdings", maxHoldings, "feeMod", self.feeMod
			self.fees = 0
		
		if self.dividends:
			if self.yesterdayValue > 0:
				self.dividendMod *= (self.yesterdayValue + self.dividends) / self.yesterdayValue
			elif todaysValue > 0:
				self.dividendMod *= (todaysValue + self.dividends) / todaysValue
			elif self.lastValue > 0:
				self.dividendMod *= (self.lastValue + self.dividends) / self.lastValue
			#print "dividends", self.dividends, "dividendMod", self.dividendMod
			self.dividends = 0
		
		#print self.day, "return", self.lastReturn
		
		for t in self.prices:
			self.yesterdayPrices[t] = self.prices[t]
		self.yesterdayValue = todaysValue
		if todaysValue:
			self.lastValue = todaysValue

	def addShares(self, ticker, shares, price):
		if shares < 0:
			raise Exception("Shares must be >= 0 for %s" % ticker)
		if price < 0:
			raise Exception("Price must be >= 0 for %s" % ticker)
		if shares == 0:
			return
		if not self.ticker:
			self.ticker = ticker
		if price != 0 or not ticker in self.prices:
			self.prices[ticker] = price
		if not ticker in self.yesterdayPrices:
			self.yesterdayPrices[ticker] = price
		if not ticker in self.cashIn:
			self.cashIn[ticker] = float(shares) * price
			self.sharesIn[ticker] = float(shares)
		else:
			self.cashIn[ticker] += float(shares) * price
			self.sharesIn[ticker] += float(shares)

	def removeShares(self, ticker, shares, price):
		if shares < 0:
			raise Exception("Shares must be >= 0 for %s" % ticker)
		if price < 0:
			raise Exception("Price must be >= 0 for %s" % ticker)
		if shares == 0:
			return
		self.prices[ticker] = price
		if not ticker in self.cashOut:
			self.cashOut[ticker] = float(shares) * price
			self.sharesOut[ticker] = float(shares)
		else:
			self.cashOut[ticker] += float(shares) * price
			self.sharesOut[ticker] += float(shares)

	def stockDividendShares(self, ticker, shares):
		if shares == 0:
			return
		if not self.ticker:
			self.ticker = ticker
		if not ticker in self.stockDividend:
			self.stockDividend[ticker] = 0.0
		self.stockDividend[ticker] += shares

	def removeSharesNoPrice(self, ticker, shares):
		if not ticker in self.prices:
			raise Exception("No price for %s" % ticker)
		self.removeShares(ticker, shares, self.prices[ticker])

	def shortShares(self, ticker, shares, price):
		if shares < 0:
			raise Exception("Shares must be >= 0 for %s" % ticker)
		if price < 0:
			raise Exception("Price must be >= 0 for %s" % ticker)
		if not self.ticker:
			self.ticker = ticker
		if price != 0:
			self.prices[ticker] = price
		# Pass a date of 1
		if not ticker in self.cashInShort:
			self.cashInShort[ticker] = 0.0
			self.sharesInShort[ticker] = 0.0
		self.cashInShort[ticker] += float(shares) * price
		self.sharesInShort[ticker] += float(shares)

	def coverShares(self, ticker, shares, price):
		if shares < 0:
			raise Exception("Shares must be >= 0 for %s" % ticker)
		if price < 0:
			raise Exception("Price must be >= 0 for %s" % ticker)
		self.prices[ticker] = price
		basis = self.basis.getBasis(ticker)
		if not ticker in self.cashOutShort:
			self.cashOutShort[ticker] = 0.0
			self.sharesOutShort[ticker] = 0.0
		self.cashOutShort[ticker] += float(shares) * price
		self.sharesOutShort[ticker] += float(shares)
		#print self.day + 1, "cover at", price, "basis", basis, "cashOut", self.cashOut, self.shares

	def addDividend(self, amount):
		if amount < 0:
			raise Exception("Amount must be >= 0 for %s" % self.ticker)
		self.dividends += amount

	def addAdjustment(self, amount):
		self.totalAdjustment += amount
		self.adjustment += amount

	def adjustBasis(self, ticker, amount):
		#if amount < 0:
		#	raise Exception("Amount must be >= 0 for %s" % ticker)
		if not ticker in self.adjustBasises:
			self.adjustBasises[ticker] = amount
		else:
			self.adjustBasises[ticker] += amount

	def addFee(self, amount):
		if amount < 0:
			raise Exception("Amount must be >= 0 for %s" % self.ticker)
		self.fees += amount

	def addDividendReinvest(self, ticker, shares, price):
		if shares < 0:
			raise Exception("Shares must be >= 0 for %s" % ticker)
		if price < 0:
			raise Exception("Price must be >= 0 for %s" % ticker)
		self.addDividend(shares * price)
		self.addShares(ticker, shares, price)

	def setValue(self, ticker, price):
		if price < 0:
			raise Exception("Price must be >= 0 for %s" % ticker)
		#print self.day + 1, "value", ticker, price
		self.prices[ticker] = price
	
	def shortValue(self, shares, basis, price, totalBasis):
		if price <= basis:
			# Positive return
			return shares * (basis - price) + totalBasis
		else:
			# Negative return
			return shares * basis * (basis / price)			

	def getTotalValue(self):
		v = 0
		for t in self.shares:
			v += self.shares[t] * self.prices[t]
		for t in self.sharesShort:
			
			v += self.shortValue(self.sharesShort[t], self.basis.getBasis(t), self.prices[t], self.basis.getTotalBasis(t))
			'''basis = self.basis.getBasis(t)
			if self.prices[t] <= basis:
				# Positive return
				v += self.sharesShort[t] * (basis - self.prices[t]) + self.basis.getTotalBasis(t)
			else:
				# Negative return
				v += self.sharesShort[t] * basis * (basis / self.prices[t])'''
		return v + self.totalAdjustment

	def getReturnSplit(self):
		return self.lastReturn

	def getReturnDiv(self):
		return self.getReturnSplit() * self.dividendMod

	def getReturnFee(self):
		return self.getReturnSplit() * self.dividendMod * self.feeMod

def checkSplit(r, check):
	if abs(r.getReturnSplit() - check) >= 1.0e-6:
		print "FAIL split:", r.getTotalValue(), r.getReturnSplit(), "split should be", check

def checkDiv(r, check):
	if abs(r.getReturnDiv() - check) >= 1.0e-6:
		print "FAIL div:", r.getTotalValue(), r.getReturnDiv(), "div should be", check

def checkFee(r, check):
	if abs(r.getReturnFee() - check) >= 1.0e-6:
		print "FAIL fee:", r.getTotalValue(), r.getReturnFee(), "fee should be", check

def checkTotalValue(r, check):
	if abs(r.getTotalValue() - check) >= 1.0e-6:
		print "FAIL total value:", r.getTotalValue(), "total value should be", check

if __name__ == "__main__":
	print "test1 - basic dividends"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.endTransactions()
	r.setValue("A", 90)
	r.endTransactions()
	checkSplit(r, 0.9)
	checkDiv(r, 0.9)
	r.setValue("A", 110)
	r.endTransactions()
	checkDiv(r, 1.1)
	r.setValue("A", 120)
	r.endTransactions()
	checkDiv(r, 1.2)

	r.beginTransactions()
	r.addDividend(100)
	r.endTransactions()
	checkSplit(r, 1.2)
	checkDiv(r, 1.3)

	print "test2 - remove shares"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.endTransactions()
	checkDiv(r, 1)

	r.beginTransactions()
	r.removeShares("A", 5, 100)
	r.endTransactions()
	checkDiv(r, 1)

	r.beginTransactions()
	r.addShares("A", 5, 100)
	r.endTransactions()
	r.setValue("A", 50)
	r.endTransactions()
	checkDiv(r, 0.5)
	r.setValue("A", 100)
	r.endTransactions()
	checkDiv(r, 1)

	print "test3 - dividends and appreciation"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.addDividend(100)
	r.endTransactions()
	checkSplit(r, 1)
	checkDiv(r, 1.1)

	r.beginTransactions()
	r.addShares("A", 5, 100)
	r.endTransactions()
	checkDiv(r, 1.1)

	r.beginTransactions()
	r.addDividend(150)
	r.setValue("A", 200)
	r.endTransactions()
	checkSplit(r, 2)
	checkDiv(r, 2.42)
	r.setValue("A", 220)
	r.endTransactions()
	checkSplit(r, 2.2)
	checkDiv(r, 2.662)

	print "test4 - dividend reinvestment"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.endTransactions()

	r.beginTransactions()
	r.addDividendReinvest("A", 1, 100)
	r.endTransactions()
	checkSplit(r, 1)
	checkDiv(r, 1.1)

	r.beginTransactions()
	r.addDividendReinvest("A", 1.1, 100)
	r.endTransactions()
	checkSplit(r, 1)
	checkDiv(r, 1.21)

	print "test5 - stocks and options"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.endTransactions()
	checkTotalValue(r, 1000)
	checkSplit(r, 1)

	r.beginTransactions()
	r.addShares("Aopt", 3, 10)
	r.endTransactions()
	checkTotalValue(r, 1030)
	checkSplit(r, 1)

	r.setValue("A", 110)
	r.endTransactions()
	checkTotalValue(r, 1130)
	checkSplit(r, 1.0970874)
	r.setValue("Aopt", 5)
	r.endTransactions()
	checkTotalValue(r, 1115)
	checkSplit(r, 1.0825243)

	r.beginTransactions()
	r.removeShares("A", 3, 110)
	r.endTransactions()
	checkTotalValue(r, 785)
	checkSplit(r, 1.0825243)
	r.setValue("A", 100)
	r.endTransactions()
	checkTotalValue(r, 715)
	checkSplit(r, 0.9859934)

	print "test6 - adds and removes at multiple prices"
	r = Twrr()
	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.addShares("A", 10, 110)
	r.endTransactions()
	checkTotalValue(r, 2200)
	checkSplit(r, 1.047619)

	r.beginTransactions()
	r.removeShares("A", 5, 110)
	r.removeShares("A", 5, 105)
	r.endTransactions()
	checkTotalValue(r, 1050)
	checkSplit(r, 1.01204481793)
	# nF should be 1073.863?

	print "test7 - single day buy/sell"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.removeShares("A", 5, 110)
	r.endTransactions()
	checkTotalValue(r, 550)
	checkSplit(r, 1.1)

	r.beginTransactions()
	r.removeShares("A", 5, 110)
	r.endTransactions()
	checkTotalValue(r, 0)
	checkSplit(r, 1.1)
	checkDiv(r, 1.1)
	checkFee(r, 1.1)

	r.beginTransactions()
	r.endTransactions()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.endTransactions()
	checkTotalValue(r, 1000)
	checkSplit(r, 1.1)

	r.beginTransactions()
	r.removeShares("A", 10, 110)
	r.endTransactions()
	checkTotalValue(r, 0)
	checkSplit(r, 1.21)

	print "test8 - changing prices multiple transactions"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.setValue("A", 110)
	r.endTransactions()
	checkTotalValue(r, 1100)
	checkSplit(r, 1.1)

	r.beginTransactions()
	r.removeShares("A", 5, 140)
	r.setValue("A", 100)
	r.endTransactions()
	checkTotalValue(r, 500)
	checkSplit(r, 1.23333333)

	print "test9 - fees"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.addFee(100)
	r.endTransactions()
	checkTotalValue(r, 1000)
	checkSplit(r, 1)
	checkDiv(r, 1)
	checkFee(r, 0.9090909)

	r.beginTransactions()
	r.addDividend(100)
	r.addFee(100)
	r.endTransactions()
	checkTotalValue(r, 1000)
	checkSplit(r, 1)
	checkDiv(r, 1.1)
	checkFee(r, 0.9090909)

	print "test10 - adjust basis"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.endTransactions()
	checkSplit(r, 1)

	r.beginTransactions()
	r.adjustBasis("A", 500)
	r.setValue("A", 50)
	r.endTransactions()
	checkSplit(r, 1)
	checkDiv(r, 1)
	checkFee(r, 1)
	checkTotalValue(r, 500)
	r.setValue("A", 60)
	r.endTransactions()
	checkTotalValue(r, 600)
	checkSplit(r, 1.2)
	checkDiv(r, 1.2)
	checkFee(r, 1.2)
	r.setValue("A", 50)
	r.endTransactions()
	checkTotalValue(r, 500)

	r.beginTransactions()
	r.adjustBasis("A", 400)
	r.setValue("A", 10)
	r.endTransactions()
	checkTotalValue(r, 100)
	checkSplit(r, 1)
	checkDiv(r, 1)
	checkFee(r, 1)

	print "test11 - adjustment"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.addAdjustment(100)
	r.endTransactions()
	checkTotalValue(r, 1100)
	checkSplit(r, 1.1)
	checkDiv(r, 1.1)
	checkFee(r, 1.1)

	r.beginTransactions()
	r.addAdjustment(300)
	r.endTransactions()
	checkTotalValue(r, 1400)
	checkSplit(r, 1.4)
	checkDiv(r, 1.4)
	checkFee(r, 1.4)

	print "test12 - dividend after closed position"
	r = Twrr()

	r.beginTransactions()
	r.addShares("A", 10, 100)
	r.endTransactions()
	checkTotalValue(r, 1000)
	checkSplit(r, 1)
	checkDiv(r, 1)
	checkFee(r, 1)

	r.beginTransactions()
	r.removeShares("A", 10, 100)
	r.endTransactions()
	checkTotalValue(r, 0)
	checkSplit(r, 1)
	checkDiv(r, 1)
	checkFee(r, 1)

	r.beginTransactions()
	r.addDividend(100)
	r.endTransactions()
	checkTotalValue(r, 0)
	checkSplit(r, 1)
	checkDiv(r, 1.1)
	checkFee(r, 1.1)

	print "test13 - basic short"
	r = Twrr()

	r.beginTransactions()
	r.shortShares("A", 10, 100)
	r.endTransactions()
	checkTotalValue(r, 1000)
	r.setValue("A", 90)
	r.endTransactions()
	checkSplit(r, 1.1)
	checkDiv(r, 1.1)
	r.setValue("A", 110)
	r.endTransactions()
	checkSplit(r, 0.9090909)

	r.beginTransactions()
	r.coverShares("A", 5, 100)
	r.endTransactions()
	r.setValue("A", 90)
	r.endTransactions()
	checkSplit(r, 1.1)
	checkDiv(r, 1.1)
	r.setValue("A", 110)
	r.endTransactions()
	checkSplit(r, 0.9090909)
	r.setValue("A", 200)
	r.endTransactions()
	checkSplit(r, 0.5)
	r.setValue("A", 300)
	r.endTransactions()
	checkSplit(r, 0.333333)
	r.setValue("A", 50)
	r.endTransactions()
	checkSplit(r, 1.5)
	r.setValue("A", 0)
	r.endTransactions()
	checkSplit(r, 2)

	print "test14 - multiple short"
	r = Twrr()

	r.beginTransactions()
	r.shortShares("A", 10, 100)
	r.endTransactions()
	checkTotalValue(r, 1000)

	r.beginTransactions()
	r.shortShares("A", 10, 90)
	r.shortShares("A", 5, 90)
	r.endTransactions()
	checkTotalValue(r, 2450)
	checkSplit(r, 1.06447368421)
	checkDiv(r, 1.06447368421)
	checkFee(r, 1.06447368421)
