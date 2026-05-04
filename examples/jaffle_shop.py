from deff import tbl

# ────────────────────────────── Data file paths ───────────────────────────── #
# Clone this repo to ~/Downloads: https://github.com/dbt-labs/jaffle_shop_duckdb/tree/duckdb
orders_path = '~/Downloads/jaffle_shop_duckdb/seeds/raw_orders.csv'
payments_path = '~/Downloads/jaffle_shop_duckdb/seeds/raw_payments.csv'
customers_path = '~/Downloads/jaffle_shop_duckdb/seeds/raw_customers.csv'


# ─────────────────── Staging tables (load the csv sources) ────────────────── #

@tbl
def stg_orders(path=orders_path):
    return f"""--sql
    from '{path}'
    select
        id as order_id,
        user_id as customer_id,
        order_date,
        status
    """
    
@tbl
def stg_payments(path=payments_path):
    return f"""--sql
    from '{path}'
    select
        id as payment_id,
        order_id,
        payment_method,
        amount / 100 as amount  -- `amount` is currently stored in cents, so we convert it to dollars
    """
    
@tbl
def stg_customers(path=customers_path):
    return f"""--sql
    from '{path}'
    select
        id as customer_id,
        first_name,
        last_name
    """


# ─────────────────────────────── Final tables ─────────────────────────────── #

@tbl
def orders(payment_methods=('credit_card', 'coupon', 'bank_transfer', 'gift_card')):

    @tbl
    def order_payments():
        return f"""--sql
        from {stg_payments}
        select
            order_id,
            {','.join([
                f"sum( if(payment_method = '{pm}', amount, 0) ) as {pm}_amount"
                for pm in payment_methods
            ])},
            sum(amount) as total_amount
        group by order_id
        """

    return f"""--sql
    from {stg_orders} left join {order_payments} using (order_id)
    select
        order_id,
        customer_id,
        order_date,
        status,
        {order_payments}.* like '%_amount',
    """
    
@tbl
def customers():

    @tbl
    def customer_orders():
        return f"""--sql
        from {stg_orders}
        select
            customer_id,
            min(order_date) as first_order,
            max(order_date) as most_recent_order,
            count(order_id) as number_of_orders
        group by customer_id
        """
        
    @tbl
    def customer_payments():
        return f"""--sql
        from {stg_payments} left join {stg_orders} using (order_id)
        select
            {stg_orders}.customer_id,
            sum(amount) as customer_lifetime_value
        group by {stg_orders}.customer_id
        """

    return f"""--sql
    from {stg_customers}
        left join {customer_orders} using (customer_id)
        left join {customer_payments} using (customer_id)
    """
