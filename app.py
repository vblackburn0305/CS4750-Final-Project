from datetime import date, datetime
from functools import wraps
from flask import (Flask, flash, redirect, render_template, request, session, url_for)
import config
from db import get_db, query
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

def required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                if session.get('role') == 'admin':
                    return redirect(url_for('customers'))
                return redirect(url_for('appointments'))
            return f(*args, **kwargs)
        return wrapper
    return decorator

@app.before_request
def keep_users_in_their_area():
    # customers only get the screens they are supposed to use.
    if session.get('role') == 'customer' and request.endpoint not in {'static', 'login', 'logout', 'register','appointments','appointment_add','purchases', 'services'}:
        return redirect(url_for('appointments'))
    # technicians can see the queue, their schedule, and service list.
    if session.get('role') == 'technician' and request.endpoint not in {'static', 'login', 'logout', 'appointments','appointment_accept', 'appointment_complete', 'technician_schedule', 'services'}:
        return redirect(url_for('appointments'))
    return None

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user'): # if you are logged in already and try to acess login, get sent to where you should be
        if session.get('role') == 'admin':
            return redirect(url_for('customers'))
        return redirect(url_for('appointments'))
    if request.method == 'POST':
        if request.form.get('username', '').strip() == config.ADMIN_USERNAME and request.form.get('password', '').strip() == config.ADMIN_PASSWORD:
            session['user'] = request.form.get('username', '').strip()
            session['role'] = 'admin'
            return redirect(url_for('customers'))
        # customers sign in with phone number and password.
        customer = query(
            '''
                SELECT customerID, customer_name
                FROM customer
                WHERE phone_number = %s AND password = %s''',
            (request.form.get('username', '').strip(), request.form.get('password', '').strip()), one=True)
        if customer:
            session['user'] = customer['customer_name']
            session['role'] = 'customer'
            session['customer_id'] = customer['customerID']
            return redirect(url_for('appointments'))
        # technicians use the same phone/password login.
        technician = query(
            '''
                SELECT technicianID, technician_name
                FROM technician
                WHERE phone = %s AND password = %s''',
            (request.form.get('username','').strip(), request.form.get('password', '').strip()), one=True)
        if technician:
            session['user'] = technician['technician_name']
            session['role'] = 'technician'
            session['technician_id'] = technician['technicianID']
            return redirect(url_for('appointments'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if not request.form.get('customer_name', '').strip() or not request.form.get('phone_number', '').strip() or not request.form.get('password', '').strip():
            flash('Name, phone number, and password are required.', 'warning')
            return render_template('customer_form.html', action='Register', customer=None)
        conn = get_db(customer=True)
        try:
            with conn.cursor() as cur:
                cur.execute('CALL customer_register(%s, %s, %s, @new_customer_id)', (request.form.get('customer_name', '').strip(),request.form.get('phone_number', '').strip(), request.form.get('password', '').strip()))
                while cur.nextset():
                    pass
                cur.execute('SELECT @new_customer_id AS customerID')
                customer_id = cur.fetchone()['customerID']
            conn.commit()
        finally:
            conn.close()
        # after registering log them in
        session['user'] = request.form.get('customer_name', '').strip()
        session['role'] = 'customer'
        session['customer_id'] = customer_id
        flash('Registration complete.', 'success')
        return redirect(url_for('appointments'))
    return render_template('customer_form.html', action='Register', customer=None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/customers', endpoint='customers')
@required("admin")
def cstmrs():
    search = request.args.get('search', '').strip()
    if search:
        rows = query(
            '''
                SELECT * FROM customer
                WHERE customer_name LIKE %s OR phone_number LIKE %s
                ORDER BY customer_name''',
            (f'%{search}%',f'%{search}%')
        )
    else:
        rows = query('SELECT * FROM customer ORDER BY customer_name')
    return render_template('customers.html', customers=rows, search=search)


@app.route('/customers/<int:cid>/edit', methods=['GET', 'POST'], endpoint='customer_edit')
@required("admin")
def cstmr(cid):
    customer = query('SELECT * FROM customer WHERE customerID = %s', (cid,), one=True)
    if not customer:
        flash('Customer not found.', 'warning')
        return redirect(url_for('customers'))
    if request.method == 'POST':
        name = request.form['customer_name'].strip()
        phone = request.form['phone_number'].strip()
        try:
            query(
                'UPDATE customer SET customer_name=%s, phone_number=%s WHERE customerID=%s',
                (name, phone, cid), commit=True
            )
            flash(f'Customer updated.', 'success')
            return redirect(url_for('customers'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    return render_template('customer_form.html', action='Edit', customer=customer)


@app.route('/appointments')
@required()
def appointments():
    date_filter = request.args.get('date', '').strip()
    status_filter = request.args.get('status', '').strip()
    if session.get('role') == 'customer':
        conn = get_db(customer=True, customer_id=session.get('customer_id'))
        try:
            with conn.cursor() as cur:
                cur.execute('CALL customer_view_appointments()')
                rows = cur.fetchall()
        finally:
            conn.close()
        if date_filter:
            filtered_rows = []
            for row in rows:
                appointment_value = row.get('appointment_date')
                if hasattr(appointment_value, 'date'):
                    appointment_day = appointment_value.date().isoformat()
                else:
                    appointment_day = str(appointment_value).split()[0]
                if appointment_day == date_filter:
                    filtered_rows.append(row)
            rows = filtered_rows
        return render_template('appointments.html', appointments=rows, technicians=[], date_filter=date_filter, tech_filter='', status_filter='')

    if session.get('role') == 'technician':
        if status_filter not in ('pending', 'completed'):
            status_filter = 'pending'

        if status_filter == 'completed':
            sql = '''
                SELECT a.appointmentID, c.customer_name, a.appointment_date, GROUP_CONCAT(o.service_name ORDER BY o.service_name SEPARATOR ", ") AS services, a.status
                FROM schedules s
                JOIN appointment a ON s.appointmentID = a.appointmentID
                JOIN customer c ON a.customerID = c.customerID
                LEFT JOIN orders o ON a.appointmentID = o.appointmentID
                WHERE s.technicianID = %s AND a.status = 'completed'
            '''
            args = [session.get('technician_id')]
        else:
            sql = '''
                SELECT a.appointmentID, c.customer_name, a.appointment_date, GROUP_CONCAT(o.service_name ORDER BY o.service_name SEPARATOR ", ") AS services, a.status
                FROM appointment a
                JOIN customer c ON a.customerID = c.customerID
                LEFT JOIN orders o ON a.appointmentID = o.appointmentID
                WHERE a.status = 'pending'
            '''
            args = []
        if date_filter:
            sql += ' AND DATE(a.appointment_date) = %s'
            args.append(date_filter)
        sql += ' GROUP BY a.appointmentID, c.customer_name, a.appointment_date, a.status'
        sql += ' ORDER BY a.appointment_date DESC, a.appointmentID DESC'
        rows = query(sql, args)
        return render_template('appointments.html', appointments=rows, technicians=[], date_filter=date_filter, tech_filter='', status_filter=status_filter)
    return redirect(url_for('customers'))

@app.route('/appointments/add', methods=['GET', 'POST'], endpoint='appointment_add')
@required()
def appt_add():
    if session.get('role') == 'customer':
        conn = get_db(customer=True, customer_id=session.get('customer_id'))
        try:
            with conn.cursor() as cur:
                cur.execute('CALL customer_view_services()')
                services_list = cur.fetchall()
        finally:
            conn.close()

        if request.method == 'POST':
            appt_date = f"{request.form['appointment_date']} {request.form['appointment_time']}"
            if not request.form.getlist('service_name'):
                flash('Please choose at least one service.', 'warning')
                return redirect(url_for('appointment_add'))

            appt_dt = datetime.strptime(appt_date, '%Y-%m-%d %H:%M')
            if appt_dt.hour < 9 or appt_dt.hour >= 17 or appt_dt.minute % 5 != 0:
                return redirect(url_for('appointment_add'))

            placeholders = ', '.join(['%s'] * len(request.form.getlist('service_name')))
            service_total = query(
                f'SELECT COUNT(*) AS service_count, SUM(service_cost) AS total FROM service WHERE service_name IN ({placeholders})',
                request.form.getlist('service_name'),
                one=True,
            )
            if service_total['service_count'] != len(request.form.getlist('service_name')):
                flash('Please choose valid services.', 'warning')
                return redirect(url_for('appointment_add'))

            conn = get_db(customer=True, customer_id=session.get('customer_id'))
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        'CALL customer_book_appointment(%s, %s, @new_appointment_id)',
                        (appt_date, service_total['total'])
                    )
                    while cur.nextset():
                        pass
                    cur.execute('SELECT @new_appointment_id AS appointmentID')
                    appt_id = cur.fetchone()['appointmentID']
                    cur.executemany(
                        'INSERT INTO orders (service_name, appointmentID) VALUES (%s,%s)',
                        [(item, appt_id) for item in request.form.getlist('service_name')]
                    )
                conn.commit()
                flash('Appointment booked successfully!', 'success')
                return redirect(url_for('appointments'))
            except Exception as e:
                conn.rollback()
                flash(f'Error booking appointment: {e}', 'danger')
            finally:
                conn.close()

        return render_template('appointment_new.html', customers=[], services=services_list, technicians=[], today=date.today().isoformat(), now=datetime.now().strftime('%Y-%m-%dT%H:%M'), customer_times=[(f'{hour:02d}:{minute:02d}', datetime.strptime(f'{hour:02d}:{minute:02d}', '%H:%M').strftime('%-I:%M %p'),) for hour in range(9, 17) for minute in range(0, 60, 5)],)

    return redirect(url_for('customers'))

@app.route('/appointments/<int:aid>/accept', methods=['POST'], endpoint='appointment_accept')
@required("technician")
def appt_accept(aid):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                '''
                    SELECT appointmentID
                    FROM appointment
                    WHERE appointmentID = %s AND status = 'pending'
                    FOR UPDATE''',
                (aid,))
            appointment = cur.fetchone()
            if not appointment:
                flash('Appointment is no longer pending.', 'warning')
                return redirect(url_for('appointments'))
            cur.execute(
                'SELECT appointmentID FROM schedules WHERE appointmentID = %s',
                (aid,))
            if cur.fetchone():
                flash('Appointment is already on a technician schedule.', 'warning')
                return redirect(url_for('appointments'))
            cur.execute(
                'INSERT INTO schedules (technicianID, appointmentID) VALUES (%s,%s)',
                (session.get('technician_id'), aid,))
            cur.execute(
                '''
                    INSERT INTO technician_schedule (technicianID, technician_date, start_time, end_time)
                    SELECT %s, DATE(appointment_date), TIME(appointment_date), ADDTIME(TIME(appointment_date), '01:00:00')
                    FROM appointment
                    WHERE appointmentID = %s AND NOT EXISTS (
                        SELECT 1
                        FROM technician_schedule
                        WHERE technicianID = %s AND technician_date = DATE(appointment.appointment_date) AND start_time = TIME(appointment.appointment_date)
                     )''',
                (session.get('technician_id'), aid, session.get('technician_id'))
            )
            cur.execute(
                "UPDATE appointment SET status = 'assigned' WHERE appointmentID = %s",
                (aid,)
            )
        conn.commit()
        flash('Appointment added to your schedule.', 'success')
        return redirect(url_for('technician_schedule'))
    except Exception as e:
        conn.rollback()
        flash(f'Error accepting appointment: {e}', 'danger')
        return redirect(url_for('appointments'))
    finally:
        conn.close()

@app.route('/technician/schedule', endpoint='technician_schedule')
@required("technician")
def tech_sched():
    date_filter = request.args.get('date', '').strip()
    status_filter = request.args.get('status', 'assigned').strip()
    if status_filter not in ('assigned', 'completed', 'all'):
        status_filter = 'assigned'

    sql = '''
        SELECT a.appointmentID, c.customer_name, a.appointment_date, GROUP_CONCAT(o.service_name ORDER BY o.service_name SEPARATOR ", ") AS services, a.status
        FROM schedules s
        JOIN appointment a ON s.appointmentID = a.appointmentID
        JOIN customer c ON a.customerID = c.customerID
        LEFT JOIN orders o ON a.appointmentID = o.appointmentID
        WHERE s.technicianID = %s AND a.status IN ('assigned', 'completed')
    '''
    args = [session.get('technician_id')]
    if status_filter != 'all':
        sql += ' AND a.status = %s'
        args.append(status_filter)
    if date_filter:
        sql += ' AND DATE(a.appointment_date) = %s'
        args.append(date_filter)
    sql += '''
        GROUP BY a.appointmentID, c.customer_name, a.appointment_date, a.status
        ORDER BY a.appointment_date ASC, a.appointmentID ASC
    '''
    rows = query(sql, args)
    return render_template('technician_schedule.html', appointments=rows, date_filter=date_filter, status_filter=status_filter)


@app.route('/appointments/<int:aid>/complete', methods=['POST'], endpoint='appointment_complete')
@required("technician")
def appt_done(aid):
    query(
        '''
            UPDATE appointment a
            JOIN schedules s ON a.appointmentID = s.appointmentID
            SET a.status = 'completed'
            WHERE a.appointmentID = %s AND s.technicianID = %s AND a.status = 'assigned' ''', 
            (aid, session.get('technician_id')), commit=True, )
    flash('Appointment marked complete.', 'success')
    return redirect(url_for('technician_schedule'))


@app.route('/purchases')
@required()
def purchases():
    if session.get('role') == 'customer':
        conn = get_db(customer=True, customer_id=session.get('customer_id'))
        try:
            with conn.cursor() as cur:
                cur.execute('CALL customer_view_purchases()')
                rows = cur.fetchall()
        finally:
            conn.close()
    else:
        rows = query(
            '''
                SELECT p.purchaseID, p.customerID, c.customer_name, p.cost, p.purchase_date
                FROM purchase p
                JOIN customer c ON p.customerID = c.customerID
                ORDER BY p.purchase_date DESC, p.purchaseID DESC'''
        )
    return render_template('purchases.html', purchases=rows)


@app.route('/services')
@required()
def services():
    if session.get('role') == 'customer':
        conn = get_db(customer=True, customer_id=session.get('customer_id'))
        try:
            with conn.cursor() as cur:
                cur.execute('CALL customer_view_services()')
                rows = cur.fetchall()
        finally:
            conn.close()
    else:
        rows = query('SELECT * FROM service ORDER BY service_name')
    return render_template('services.html', services=rows)


@app.route('/services/add', methods=['POST'])
@required("admin")
def service_add():
    try:
        query('INSERT INTO service (service_name, service_cost) VALUES (%s,%s)',
              (request.form['service_name'].strip(), request.form['service_cost'].strip()), commit=True)
        flash(f'Service "{request.form["service_name"].strip()}" added.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('services'))


@app.route('/services/<path:name>/delete', methods=['POST'])
@required("admin")
def service_delete(name):
    try:
        query('DELETE FROM service WHERE service_name=%s', (name,), commit=True)
        flash(f'Service deleted.', 'success')
    except Exception as e:
        flash(f'Cannot delete — service may be linked to appointments.', 'danger')
    return redirect(url_for('services'))


@app.route('/products')
@required("admin")
def products():
    type_filter = request.args.get('type', '').strip()
    if type_filter:
        rows = query(
            'SELECT * FROM product WHERE product_type=%s ORDER BY product_name',
            (type_filter,)
        )
    else:
        rows = query('SELECT * FROM product ORDER BY product_type, product_name')
    types = query('SELECT DISTINCT product_type FROM product ORDER BY product_type')
    return render_template('products.html', products=rows, types=types, type_filter=type_filter)


@app.route('/products/update', methods=['POST'])
@required("admin")
def product_update():
    try:
        query('UPDATE product SET stock_quantity=%s WHERE product_name=%s',
              (request.form['stock_quantity'], request.form['product_name']), commit=True)
        flash(
            'Stock for "' + request.form['product_name'] + '" updated to '
            + request.form['stock_quantity'] + '.',
            'success',
        )
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('products'))


@app.route('/products/add', methods=['POST'])
@required("admin")
def product_add():
    flash('Products are added from supply orders now.', 'warning')
    return redirect(url_for('products'))


@app.route('/products/<path:name>/delete', methods=['POST'])
@required("admin")
def product_delete(name):
    try:
        query('DELETE FROM product WHERE product_name=%s', (name,), commit=True)
        flash(f'Product deleted.', 'success')
    except Exception as e:
        flash(f'Cannot delete — product may be in use.', 'danger')
    return redirect(url_for('products'))


@app.route('/technicians')
@required("admin")
def technicians():
    rows = query(
        '''
            SELECT t.technicianID, t.technician_name, t.phone, COUNT(DISTINCT s.appointmentID) AS total_appts
            FROM technician t
            LEFT JOIN schedules s ON t.technicianID = s.technicianID
            GROUP BY t.technicianID, t.technician_name, t.phone
            ORDER BY t.technician_name'''
    )
    return render_template('technicians.html', technicians=rows)


@app.route('/technicians/add', methods=['POST'])
@required("admin")
def technician_add():
    name = request.form['technician_name'].strip()
    phone = request.form['phone'].strip()
    try:
        query('INSERT INTO technician (technician_name, phone) VALUES (%s,%s)',
              (name, phone), commit=True)
        flash(f'Technician "{name}" added.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('technicians'))


@app.route('/technicians/<int:tid>/delete', methods=['POST'])
@required("admin")
def technician_delete(tid):
    try:
        query('DELETE FROM technician WHERE technicianID=%s', (tid,), commit=True)
        flash('Technician removed.', 'success')
    except Exception as e:
        flash(f'Cannot delete — technician may have scheduled appointments.', 'danger')
    return redirect(url_for('technicians'))


@app.route('/supply-orders', endpoint='supply_orders')
@required("admin")
def supps():
    orders = query(
        '''
            SELECT so.orderID, so.order_date, so.delivery_date, so.cost, so.status, sup.supplier_name, sup.city
            FROM supply_order so
            JOIN supplier sup ON so.supplierID = sup.supplierID
            ORDER BY so.order_date DESC, so.orderID DESC'''
    )
    suppliers = query('SELECT * FROM supplier ORDER BY supplier_name')
    return render_template('supply_orders.html', orders=orders, suppliers=suppliers)


@app.route('/supply-orders/add', methods=['POST'], endpoint='supply_order_add')
@required("admin")
def supp_add():
    supplier_id = request.form.get('supplierID')
    if request.form.get('new_supplier_name', '').strip():
        supplier_id = query(
            'INSERT INTO supplier (supplier_name, city, phone_number) VALUES (%s,%s,%s)',
            (request.form['new_supplier_name'].strip(), request.form.get('new_supplier_city', '').strip(), request.form.get('new_supplier_phone', '').strip(),), commit=True,)
    try:
        order_id = query(
            'INSERT INTO supply_order (supplierID, cost, order_date, delivery_date, status) VALUES (%s,%s,%s,%s,%s)',
            (supplier_id, request.form['cost'], request.form['order_date'], request.form['delivery_date'], 'pending'),
            commit=True,
        )
        flash('Supply order added. Add the products included in the order.', 'success')
        return redirect(url_for('supply_order_items', order_id=order_id))
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('supply_orders'))


@app.route('/supply-orders/<int:order_id>/items', endpoint='supply_order_items')
@required("admin")
def supp_items(order_id):
    order = query(
        '''
            SELECT so.orderID, so.order_date, so.delivery_date, so.cost, so.status, sup.supplier_name
            FROM supply_order so
            JOIN supplier sup ON so.supplierID = sup.supplierID
            WHERE so.orderID = %s''', (order_id,), one=True)
    if not order:
        flash('Supply order not found.', 'warning')
        return redirect(url_for('supply_orders'))
    items = query(
        '''
            SELECT sop.product_name, sop.quantity, p.product_type
            FROM includes sop
            JOIN product p ON sop.product_name = p.product_name
            WHERE sop.orderID = %s
            ORDER BY sop.product_name''', (order_id,))
    products = query('SELECT * FROM product ORDER BY product_type, product_name')
    return render_template('supply_order_items.html', order=order, items=items, products=products)


@app.route('/supply-orders/<int:order_id>/items/update', methods=['POST'], endpoint='supply_order_item_update')
@required("admin")
def supp_item_upd(order_id):
    order = query('SELECT status FROM supply_order WHERE orderID=%s', (order_id,), one=True)
    if not order or order['status'] == 'delivered':
        return redirect(url_for('supply_orders'))
    if int(request.form['quantity']) > 0:
        query(
            '''
                INSERT INTO includes (orderID, product_name, quantity)
                VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE quantity = VALUES(quantity)''', 
                (order_id, request.form['product_name'], request.form['quantity']), commit=True)
    return redirect(url_for('supply_order_items', order_id=order_id))


@app.route('/supply-orders/<int:order_id>/items/add-product', methods=['POST'], endpoint='supply_order_item_add_product')
@required("admin")
def supp_item_new(order_id):
    order = query('SELECT status FROM supply_order WHERE orderID=%s', (order_id,), one=True)
    if not order or order['status'] == 'delivered':
        return redirect(url_for('supply_orders'))
    query(
        '''
            INSERT INTO product (product_name, stock_quantity, product_type)
            VALUES (%s,0,%s)
            ON DUPLICATE KEY UPDATE product_type = VALUES(product_type)''',
        (request.form['product_name'].strip(), request.form['product_type'].strip()), commit=True)
    query(
        '''
            INSERT INTO includes (orderID, product_name, quantity)
            VALUES (%s,%s,%s)
            ON DUPLICATE KEY UPDATE quantity = VALUES(quantity)''',
        (order_id, request.form['product_name'].strip(), request.form['quantity']), commit=True)
    return redirect(url_for('supply_order_items', order_id=order_id))


@app.route('/supply-orders/<int:order_id>/arrive', methods=['POST'], endpoint='supply_order_arrive')
@required("admin")
def supp_arrive(order_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT status FROM supply_order WHERE orderID=%s', (order_id,))
            order = cur.fetchone()
            if not order or order['status'] == 'delivered':
                return redirect(url_for('supply_orders'))
            cur.execute('SELECT product_name, quantity FROM includes WHERE orderID=%s', (order_id,))
            for item in cur.fetchall():
                cur.execute(
                    'UPDATE product SET stock_quantity = stock_quantity + %s WHERE product_name=%s',
                    (item['quantity'], item['product_name']),
                )
            cur.execute("UPDATE supply_order SET status='delivered' WHERE orderID=%s", (order_id,))
        conn.commit()
        flash('Supply order marked delivered. Inventory updated.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('supply_orders'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
