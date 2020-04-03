/* Welcome to the SQL mini project. For this project, you will use
Springboard' online SQL platform, which you can log into through the
following link:

https://sql.springboard.com/
Username: student
Password: learn_sql@springboard

The data you need is in the "country_club" database. This database
contains 3 tables:
    i) the "Bookings" table,
    ii) the "Facilities" table, and
    iii) the "Members" table.

Note that, if you need to, you can also download these tables locally.

In the mini project, you'll be asked a series of questions. You can
solve them using the platform, but for the final deliverable,
paste the code for each solution into this script, and upload it
to your GitHub.

Before starting with the questions, feel free to take your time,
exploring the data, and getting acquainted with the 3 tables. */



/* Q1: Some of the facilities charge a fee to members, but some do not.
Please list the names of the facilities that do. */

SELECT name
FROM Facilities
WHERE membercost > 0


/* Q2: How many facilities do not charge a fee to members? */

SELECT COUNT(name)
FROM Facilities
WHERE membercost = 0 

/* Q3: How can you produce a list of facilities that charge a fee to members,
where the fee is less than 20% of the facility's monthly maintenance cost?
Return the facid, facility name, member cost, and monthly maintenance of the
facilities in question. */

SELECT facid,
		name,
		membercost,
		monthlymaintenance
FROM Facilities
WHERE membercost < 0.2 * monthlymaintenance AND membercost > 0 
/* Does membercost = 0 count as where the fee is less than maintenance cost?
Remove AND statement if so. */


/* Q4: How can you retrieve the details of facilities with ID 1 and 5?
Write the query without using the OR operator. */

SELECT *
FROM Facilities
WHERE facid IN (1, 5)


/* Q5: How can you produce a list of facilities, with each labelled as
'cheap' or 'expensive', depending on if their monthly maintenance cost is
more than $100? Return the name and monthly maintenance of the facilities
in question. */

SELECT name,
		monthlymaintenance,
		CASE WHEN monthlymaintenance < 100 
				THEN 'cheap' 
			WHEN monthlymaintenance >= 100 
				THEN 'expensive'
			ELSE NULL 
		END as price_category
FROM Facilities
/* Premise doesn't indicate how to handle monthlymaintenance=100
so I'm calling it expensive because I'm a poor graduate student. */ 



/* Q6: You'd like to get the first and last name of the last member(s)
who signed up. Do not use the LIMIT clause for your solution. */

SELECT firstname, 
	surname, 
	joindate 
FROM Members
WHERE joindate=(
					SELECT MAX(joindate) 
					FROM Members
				)

/* Q7: How can you produce a list of all members who have used a tennis court?
Include in your output the name of the court, and the name of the member
formatted as a single column. Ensure no duplicate data, and order by
the member name. */

SELECT CONCAT(firstname, ' ', surname) AS fullname,
		name AS facility_name
FROM Members
	JOIN Facilities 
	WHERE name IN ('Tennis Court 1', 'Tennis Court 2')
GROUP BY CONCAT(firstname, ' ', surname)
ORDER BY fullname


/* Q8: How can you produce a list of bookings on the day of 2012-09-14 which
will cost the member (or guest) more than $30? Remember that guests have
different costs to members (the listed costs are per half-hour 'slot'), and
the guest user's ID is always 0. Include in your output the name of the
facility, the name of the member formatted as a single column, and the cost.
Order by descending cost, and do not use any subqueries. */

SELECT CONCAT(Members.firstname, ' ', Members.surname) AS fullname,
		Facilities.name as facility_name,
		CASE WHEN Bookings.memid = 0 
				THEN Bookings.slots * Facilities.guestcost
			WHEN Bookings.memid != 0 
				THEN Bookings.slots * Facilities.membercost
			ELSE NULL 
		END as total_booking_cost
FROM Bookings
JOIN Facilities
	ON Facilities.facid = Bookings.facid
JOIN Members 
	ON Members.memid = Bookings.memid
	WHERE Bookings.starttime LIKE '%2012-09-14%'
		AND ((Bookings.slots * Facilities.guestcost > 30
			AND Bookings.memid = 0 ) 
		OR 
			(Bookings.slots * Facilities.membercost > 30
				AND Bookings.memid != 0 ) )
ORDER BY total_booking_cost DESC



/* Q9: This time, produce the same result as in Q8, but using a subquery. */

SELECT CONCAT(x.firstname, ' ', x.surname) AS fullname,
		y.name as facility_name,
		y.total_booking_cost as total_booking_cost
FROM
(
	SELECT Members.memid as memid,
 		Members.surname as surname,
 		Members.firstname as firstname
	FROM Members

)	
AS x     
INNER JOIN
(
	SELECT  
		Bookings.memid,
		Bookings.starttime,
		Facilities.name,
		Bookings.slots,
		CASE WHEN Bookings.memid = 0 
				THEN Bookings.slots * Facilities.guestcost
			 WHEN Bookings.memid != 0 
				THEN Bookings.slots * Facilities.membercost
			 ELSE NULL 
		END AS total_booking_cost
	FROM Bookings
		JOIN 
			Facilities
		ON Facilities.facid = Bookings.facid
) 
AS y 
ON y.memid = x.memid
	WHERE y.starttime LIKE '%2012-09-14%'
		AND total_booking_cost > 30
ORDER BY total_booking_cost DESC



/* Q10: Produce a list of facilities with a total revenue less than 1000.
The output of facility name and total revenue, sorted by revenue. Remember
that there's a different cost for guests and members! */

SELECT 	SUM(Y.revenue) as revenue,
		Y.facility_name as facility_name
FROM
		(	SELECT Bookings.memid,
         			Bookings.slots,
         			Facilities.name as facility_name,
        			(
						CASE WHEN Bookings.memid = 0 
								THEN Facilities.guestcost * Bookings.slots 
								ELSE 0 
							END
						+ 
						CASE WHEN Bookings.memid != 0 
							THEN Facilities.membercost * Bookings.slots 
							ELSE 0 
							END
					) 	
					AS revenue
			FROM Bookings
			JOIN Facilities
        	ON Facilities.facid = Bookings.facid
		) 	
		AS Y
GROUP BY facility_name HAVING revenue < 1000
ORDER BY revenue DESC


		