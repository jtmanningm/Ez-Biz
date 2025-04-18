import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
from models.service import ServiceModel
from utils.formatting import format_currency, format_date, format_time, add_back_navigation
from database.connection import SnowflakeConnection
from utils.null_handling import safe_get_float, safe_get_int, safe_get_string, safe_get_bool

def store_service_session_data(row: pd.Series) -> None:
    """
    Safely store service data in session state with proper null handling.
    
    Args:
        row: DataFrame row containing service information
    """
    st.session_state['selected_service'] = {
        'TRANSACTION_ID': safe_get_int(row['TRANSACTION_ID']),
        'SERVICE_ID': safe_get_int(row['SERVICE_ID']),  # This was previously allowing None
        'CUSTOMER_OR_ACCOUNT_ID': (
            safe_get_int(row['ACCOUNT_ID']) if pd.notnull(row['ACCOUNT_ID']) 
            else safe_get_int(row['CUSTOMER_ID'])
        ),
        'CUSTOMER_NAME': safe_get_string(row['CUSTOMER_NAME']),
        'SERVICE_NAME': safe_get_string(row['SERVICE_NAME']),
        'SERVICE_DATE': row['SERVICE_DATE'],
        'SERVICE_TIME': row['START_TIME'],
        'NOTES': safe_get_string(row['COMMENTS']),
        'DEPOSIT': safe_get_float(row['DEPOSIT']),
        'DEPOSIT_PAID': safe_get_bool(row['DEPOSIT_PAID']),
        'COST': safe_get_float(row['BASE_SERVICE_COST']),
    }
    st.session_state['service_start_time'] = datetime.now().time()
    st.session_state['page'] = 'transaction_details'

def update_service_status(snowflake_conn: SnowflakeConnection, transaction_id: int, status: str = 'IN_PROGRESS') -> None:
    """
    Update the status of a service transaction.
    
    Args:
        snowflake_conn: Snowflake connection instance
        transaction_id: ID of the transaction to update
        status: New status to set
    """
    update_query = """
    UPDATE OPERATIONAL.CARPET.SERVICE_TRANSACTION
    SET STATUS = :1,
        START_TIME = CURRENT_TIME(),
        LAST_MODIFIED_DATE = CURRENT_TIMESTAMP()
    WHERE ID = :2
    """
    try:
        snowflake_conn.execute_query(update_query, [status, transaction_id])
    except Exception as e:
        st.error(f"Failed to update service status: {str(e)}")
        raise

def handle_deposit_confirmation(snowflake_conn: SnowflakeConnection, transaction_id: int) -> None:
    """Handle deposit confirmation logic"""
    update_query = """
    UPDATE OPERATIONAL.CARPET.SERVICE_TRANSACTION
    SET DEPOSIT_PAID = TRUE,
        LAST_MODIFIED_DATE = CURRENT_TIMESTAMP()
    WHERE ID = ?
    """
    snowflake_conn.execute_query(update_query, [transaction_id])
    st.session_state.deposit_confirmation_state = transaction_id

def handle_service_start(snowflake_conn: SnowflakeConnection, row: pd.Series) -> None:
    """Handle service start logic"""
    transaction_id = safe_get_int(row['TRANSACTION_ID'])
    
    # Store service information in session state
    st.session_state['selected_service'] = {
        'TRANSACTION_ID': transaction_id,
        'SERVICE_ID': safe_get_int(row['SERVICE_ID']),
        'CUSTOMER_OR_ACCOUNT_ID': (
            safe_get_int(row['ACCOUNT_ID']) 
            if pd.notnull(row['ACCOUNT_ID']) 
            else safe_get_int(row['CUSTOMER_ID'])
        ),
        'CUSTOMER_NAME': safe_get_string(row['CUSTOMER_NAME']),
        'SERVICE_NAME': safe_get_string(row['SERVICE_NAME']),
        'SERVICE_DATE': row['SERVICE_DATE'],
        'SERVICE_TIME': row['START_TIME'],
        'NOTES': safe_get_string(row['COMMENTS']),
        'DEPOSIT': safe_get_float(row['DEPOSIT']),
        'DEPOSIT_PAID': safe_get_bool(row['DEPOSIT_PAID']),
        'BASE_SERVICE_COST': safe_get_float(row['BASE_SERVICE_COST']),
        'SERVICE_ADDRESS': safe_get_string(row['SERVICE_ADDRESS']),
        'SERVICE_CITY': safe_get_string(row['SERVICE_CITY']),
        'SERVICE_STATE': safe_get_string(row['SERVICE_STATE']),
        'SERVICE_ZIP': safe_get_int(row['SERVICE_ZIP'])
    }
    
    # Update service status
    update_query = """
    UPDATE OPERATIONAL.CARPET.SERVICE_TRANSACTION
    SET STATUS = 'IN_PROGRESS',
        START_TIME = CURRENT_TIME(),
        LAST_MODIFIED_DATE = CURRENT_TIMESTAMP()
    WHERE ID = ?
    """
    snowflake_conn.execute_query(update_query, [transaction_id])
    
    st.session_state['service_start_time'] = datetime.now().time()
    st.session_state['page'] = 'transaction_details'

def render_service_card(row: pd.Series, snowflake_conn: SnowflakeConnection) -> None:
    """Render a single service card with all its details and actions."""
    with st.container():
        col1, col2, col3 = st.columns([2, 3, 1])

        # Time column
        with col1:
            st.write(f"🕒 {format_time(row['START_TIME'])}")

        # Service details column
        with col2:
            # Customer and Service Info
            service_info = f"📋 {row['SERVICE_NAME']} - {row['CUSTOMER_NAME']}"
            
            # Service Address
            address_parts = [
                safe_get_string(row['SERVICE_ADDRESS']),
                safe_get_string(row['SERVICE_CITY']),
                safe_get_string(row['SERVICE_STATE']),
                str(safe_get_int(row['SERVICE_ZIP']))
            ]
            address = ', '.join(filter(None, address_parts))
            if address:
                service_info += f"\n📍 {address}"

            # Deposit Info
            deposit_amount = safe_get_float(row['DEPOSIT'])
            deposit_paid = safe_get_bool(row['DEPOSIT_PAID'])
            
            if deposit_amount > 0:
                payment_status = "✅ Deposit Paid" if deposit_paid else "⚠️ Deposit Required"
                service_info += f"\n💰 {payment_status}: {format_currency(deposit_amount)}"

            # Recurring Service Info
            if safe_get_bool(row['IS_RECURRING']):
                service_info += f"\n🔄 {row['RECURRENCE_PATTERN']} Service"

            # Notes
            if pd.notnull(row['COMMENTS']):
                service_info += f"\n📝 {row['COMMENTS']}"

            st.write(service_info)

        # Actions column
        with col3:
            transaction_id = safe_get_int(row['TRANSACTION_ID'])
            unique_key_prefix = f"{transaction_id}_{row['SERVICE_DATE'].strftime('%Y%m%d')}"

            # Handle deposit confirmation and start button logic
            if deposit_amount > 0:
                if not deposit_paid:
                    # Only show confirm deposit button when deposit isn't paid
                    if st.session_state.deposit_confirmation_state == transaction_id:
                        st.success("Deposit confirmed!")
                        if st.button("Continue", key=f"continue_{unique_key_prefix}"):
                            st.session_state.deposit_confirmation_state = None
                            st.rerun()
                    else:
                        if st.button("Confirm Deposit", key=f"confirm_deposit_{unique_key_prefix}"):
                            handle_deposit_confirmation(snowflake_conn, transaction_id)
                            st.rerun()
                elif row['STATUS'] == 'SCHEDULED':
                    # Only show start button after deposit is confirmed
                    if st.button("✓ Start", key=f"start_{unique_key_prefix}"):
                        handle_service_start(snowflake_conn, row)
                        st.rerun()
            else:
                # If no deposit required, show start button directly
                if row['STATUS'] == 'SCHEDULED':
                    if st.button("✓ Start", key=f"start_{unique_key_prefix}"):
                        handle_service_start(snowflake_conn, row)
                        st.rerun()

def scheduled_services_page():
    """Display scheduled services page with improved error handling"""
    try:
        snowflake_conn = SnowflakeConnection.get_instance()
    except Exception as e:
        st.error(f"Failed to connect to database: {str(e)}")
        return

    st.title('Scheduled Services')
    add_back_navigation()

    # Initialize confirmation state
    if 'deposit_confirmation_state' not in st.session_state:
        st.session_state.deposit_confirmation_state = None

    # Date range selection
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=datetime.now().date())
    with col2:
        end_date = st.date_input("End Date", value=datetime.now().date() + timedelta(days=30))

    try:
        query = """
        WITH RankedAddresses AS (
            SELECT 
                CUSTOMER_ID,
                STREET_ADDRESS,
                CITY,
                STATE,
                ZIP_CODE,
                ROW_NUMBER() OVER (PARTITION BY CUSTOMER_ID ORDER BY 
                    CASE WHEN IS_PRIMARY_SERVICE = TRUE THEN 0 ELSE 1 END,
                    CREATED_AT DESC
                ) as rn
            FROM OPERATIONAL.CARPET.SERVICE_ADDRESSES
        )
        SELECT DISTINCT
            ST.ID as TRANSACTION_ID,
            S.SERVICE_ID,
            S.SERVICE_NAME,
            ST.CUSTOMER_ID,
            ST.ACCOUNT_ID,
            ST.DEPOSIT,
            ST.DEPOSIT_PAID,
            ST.SERVICE_DATE,
            ST.START_TIME,
            ST.STATUS,
            C.FIRST_NAME || ' ' || C.LAST_NAME as CUSTOMER_NAME,  
            ST.COMMENTS,
            ST.IS_RECURRING,
            ST.RECURRENCE_PATTERN,
            COALESCE(ST.BASE_SERVICE_COST, ST.AMOUNT) as BASE_SERVICE_COST,  -- Use AMOUNT if BASE_SERVICE_COST is null
            RA.STREET_ADDRESS as SERVICE_ADDRESS,
            RA.CITY as SERVICE_CITY,
            RA.STATE as SERVICE_STATE,
            RA.ZIP_CODE as SERVICE_ZIP
        FROM OPERATIONAL.CARPET.SERVICE_TRANSACTION ST
        LEFT JOIN OPERATIONAL.CARPET.SERVICES S ON ST.SERVICE_ID = S.SERVICE_ID
        LEFT JOIN OPERATIONAL.CARPET.CUSTOMER C ON ST.CUSTOMER_ID = C.CUSTOMER_ID
        LEFT JOIN RankedAddresses RA ON ST.CUSTOMER_ID = RA.CUSTOMER_ID AND RA.rn = 1
        WHERE ST.SERVICE_DATE >= ?
        AND ST.SERVICE_DATE <= ?
        AND ST.STATUS IN ('SCHEDULED', 'IN_PROGRESS')  -- Include both statuses
        ORDER BY ST.SERVICE_DATE, ST.START_TIME;
        """
        
        services_df = pd.DataFrame(snowflake_conn.execute_query(query, [start_date, end_date]))
        
        if not services_df.empty:
            current_date = None
            
            for _, row in services_df.iterrows():
                if current_date != row['SERVICE_DATE']:
                    current_date = row['SERVICE_DATE']
                    st.markdown(f"### {format_date(current_date)}")
                
                render_service_card(row, snowflake_conn)

            # Summary statistics
            render_summary_statistics(services_df)
        else:
            st.info("No services scheduled for the selected date range.")
            
    except Exception as e:
        st.error(f"Failed to load scheduled services: {str(e)}")
        if st.session_state.get('debug_mode'):
            st.exception(e)

def render_summary_statistics(services_df: pd.DataFrame) -> None:
    """
    Render summary statistics with proper null handling.
    
    Args:
        services_df: DataFrame containing services information
    """
    st.markdown("### Summary")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Services", len(services_df))

    with col2:
        pending_deposits = len(services_df[
            (services_df['DEPOSIT'].notna()) & 
            (services_df['DEPOSIT'] > 0) &
            (~services_df['DEPOSIT_PAID'].fillna(False))
        ])
        st.metric("Pending Deposits", pending_deposits)

    with col3:
        confirmed_deposits = len(services_df[
            (services_df['DEPOSIT'].notna()) &
            (services_df['DEPOSIT'] > 0) &
            (services_df['DEPOSIT_PAID'] == True)
        ])
        st.metric("Confirmed Deposits", confirmed_deposits)